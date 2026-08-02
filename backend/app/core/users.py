from collections.abc import Generator
from typing import Any

from fastapi import Depends, Request
from fastapi.security import OAuth2PasswordRequestForm
from fastapi_users import BaseUserManager, exceptions
from fastapi_users.db import BaseUserDatabase
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.core.security import password_helper
from app.db.session import get_db
from app.models import OAuthAccount, User


def _initial(name: str) -> str:
    return (name.strip()[:1] or "?").upper()


class SyncSQLAlchemyUserDatabase(BaseUserDatabase[User, str]):
    """Async FastAPI Users adapter over the existing synchronous SQLAlchemy stack.

    Every blocking database operation crosses an explicit thread-pool boundary;
    no synchronous Session query runs on the ASGI event-loop thread.
    """

    def __init__(self, session: Session):
        self.session = session

    async def get(self, id: str) -> User | None:
        return await run_in_threadpool(self.session.get, User, id)

    async def get_by_email(self, email: str) -> User | None:
        def operation():
            return self.session.query(User).filter(User.email == email).first()

        return await run_in_threadpool(operation)

    async def get_by_oauth_account(self, oauth: str, account_id: str) -> User | None:
        def operation():
            account = (
                self.session.query(OAuthAccount)
                .filter(OAuthAccount.oauth_name == oauth, OAuthAccount.account_id == account_id)
                .first()
            )
            return self.session.get(User, account.user_id) if account else None

        return await run_in_threadpool(operation)

    async def create(self, create_dict: dict[str, Any]) -> User:
        values = self._normalize_user_values(create_dict, creating=True)

        def operation():
            try:
                user = User(**values)
                self.session.add(user)
                self.session.commit()
                self.session.refresh(user)
                return user
            except IntegrityError as exc:
                self.session.rollback()
                # Close the check-then-insert race between concurrent signups.
                raise exceptions.UserAlreadyExists() from exc
            except Exception:
                self.session.rollback()
                raise

        return await run_in_threadpool(operation)

    async def update(self, user: User, update_dict: dict[str, Any]) -> User:
        values = self._normalize_user_values(update_dict, creating=False)

        def operation():
            try:
                for key, value in values.items():
                    setattr(user, key, value)
                self.session.commit()
                self.session.refresh(user)
                return user
            except Exception:
                self.session.rollback()
                raise

        return await run_in_threadpool(operation)

    async def delete(self, user: User) -> None:
        def operation():
            try:
                self.session.delete(user)
                self.session.commit()
            except Exception:
                self.session.rollback()
                raise

        await run_in_threadpool(operation)

    async def add_oauth_account(self, user: User, create_dict: dict[str, Any]) -> User:
        def operation():
            try:
                account = OAuthAccount(user_id=user.id, **create_dict)
                self.session.add(account)
                self.session.commit()
                self.session.refresh(user)
                return user
            except Exception:
                self.session.rollback()
                raise

        return await run_in_threadpool(operation)

    async def update_oauth_account(
        self,
        user: User,
        oauth_account: OAuthAccount,
        update_dict: dict[str, Any],
    ) -> User:
        def operation():
            try:
                for key, value in update_dict.items():
                    setattr(oauth_account, key, value)
                self.session.commit()
                self.session.refresh(user)
                return user
            except Exception:
                self.session.rollback()
                raise

        return await run_in_threadpool(operation)

    def _normalize_user_values(self, values: dict[str, Any], *, creating: bool) -> dict[str, Any]:
        data = dict(values)
        avatar = data.pop("avatar", None)
        if avatar is not None and str(avatar).strip():
            data["avatar_initial"] = str(avatar).strip()[:4]
        display_name = str(data.get("display_name") or "").strip()
        if display_name:
            data["display_name"] = display_name
            if "avatar_initial" not in data:
                data["avatar_initial"] = _initial(display_name)
        elif creating:
            fallback = str(data.get("email") or "User").split("@", 1)[0] or "User"
            data["display_name"] = fallback
            data["avatar_initial"] = _initial(fallback)
        return data


def get_user_db(db: Session = Depends(get_db)) -> Generator[SyncSQLAlchemyUserDatabase, None, None]:
    yield SyncSQLAlchemyUserDatabase(db)


class UserManager(BaseUserManager[User, str]):
    reset_password_token_secret = settings.JWT_SECRET
    verification_token_secret = settings.JWT_SECRET

    def __init__(self, user_db: SyncSQLAlchemyUserDatabase):
        super().__init__(user_db, password_helper=password_helper)

    def parse_id(self, value: Any) -> str:
        if isinstance(value, str) and value:
            return value
        raise exceptions.InvalidID()

    async def validate_password(self, password: str, user: User | Any) -> None:
        if len(password) < 6:
            raise exceptions.InvalidPasswordException(reason="Password should be at least 6 characters")

    async def create(self, user_create, safe: bool = False, request: Request | None = None) -> User:
        await self.validate_password(user_create.password, user_create)
        if await self.user_db.get_by_email(user_create.email) is not None:
            raise exceptions.UserAlreadyExists()
        user_dict = (
            user_create.create_update_dict()
            if safe
            else user_create.create_update_dict_superuser()
        )
        password = user_dict.pop("password")
        user_dict["hashed_password"] = await run_in_threadpool(
            self.password_helper.hash,
            password,
        )
        created_user = await self.user_db.create(user_dict)
        await self.on_after_register(created_user, request)
        return created_user

    async def authenticate(self, credentials: OAuth2PasswordRequestForm) -> User | None:
        try:
            user = await self.get_by_email(credentials.username)
        except exceptions.UserNotExists:
            # Keep the invalid-email timing path, but move the expensive hash
            # away from the event loop as well.
            await run_in_threadpool(self.password_helper.hash, credentials.password)
            return None
        verified, updated_hash = await run_in_threadpool(
            self.password_helper.verify_and_update,
            credentials.password,
            user.hashed_password,
        )
        if not verified:
            return None
        if updated_hash is not None:
            user = await self.user_db.update(user, {"hashed_password": updated_hash})
        return user

    async def _update(self, user: User, update_dict: dict[str, Any]) -> User:
        validated: dict[str, Any] = {}
        for field, value in update_dict.items():
            if field == "email" and value != user.email:
                try:
                    await self.get_by_email(value)
                    raise exceptions.UserAlreadyExists()
                except exceptions.UserNotExists:
                    validated["email"] = value
                    validated["is_verified"] = False
            elif field == "password" and value is not None:
                await self.validate_password(value, user)
                validated["hashed_password"] = await run_in_threadpool(
                    self.password_helper.hash,
                    value,
                )
            else:
                validated[field] = value
        return await self.user_db.update(user, validated)

    async def on_after_forgot_password(self, user: User, token: str, request: Request | None = None) -> None:
        # Hook point for a real mailer. The route exists now; production can wire email delivery here.
        return None

    async def on_after_request_verify(self, user: User, token: str, request: Request | None = None) -> None:
        # Hook point for a real mailer. The route exists now; production can wire email delivery here.
        return None
