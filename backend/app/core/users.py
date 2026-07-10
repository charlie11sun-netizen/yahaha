from collections.abc import Generator
from typing import Any

from fastapi import Depends, Request
from fastapi_users import BaseUserManager, exceptions
from fastapi_users.db import BaseUserDatabase
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import password_helper
from app.db.session import get_db
from app.models import OAuthAccount, User


def _initial(name: str) -> str:
    return (name.strip()[:1] or "?").upper()


class SyncSQLAlchemyUserDatabase(BaseUserDatabase[User, str]):
    """FastAPI Users database adapter for this app's existing sync SQLAlchemy stack."""

    def __init__(self, session: Session):
        self.session = session

    async def get(self, id: str) -> User | None:
        return self.session.get(User, id)

    async def get_by_email(self, email: str) -> User | None:
        return self.session.query(User).filter(User.email == email).first()

    async def get_by_oauth_account(self, oauth: str, account_id: str) -> User | None:
        account = (
            self.session.query(OAuthAccount)
            .filter(OAuthAccount.oauth_name == oauth, OAuthAccount.account_id == account_id)
            .first()
        )
        return self.session.get(User, account.user_id) if account else None

    async def create(self, create_dict: dict[str, Any]) -> User:
        values = self._normalize_user_values(create_dict, creating=True)
        user = User(**values)
        self.session.add(user)
        self.session.commit()
        self.session.refresh(user)
        return user

    async def update(self, user: User, update_dict: dict[str, Any]) -> User:
        values = self._normalize_user_values(update_dict, creating=False)
        for key, value in values.items():
            setattr(user, key, value)
        self.session.commit()
        self.session.refresh(user)
        return user

    async def delete(self, user: User) -> None:
        self.session.delete(user)
        self.session.commit()

    async def add_oauth_account(self, user: User, create_dict: dict[str, Any]) -> User:
        account = OAuthAccount(user_id=user.id, **create_dict)
        self.session.add(account)
        self.session.commit()
        self.session.refresh(user)
        return user

    async def update_oauth_account(
        self,
        user: User,
        oauth_account: OAuthAccount,
        update_dict: dict[str, Any],
    ) -> User:
        for key, value in update_dict.items():
            setattr(oauth_account, key, value)
        self.session.commit()
        self.session.refresh(user)
        return user

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

    async def on_after_forgot_password(self, user: User, token: str, request: Request | None = None) -> None:
        # Hook point for a real mailer. The route exists now; production can wire email delivery here.
        return None

    async def on_after_request_verify(self, user: User, token: str, request: Request | None = None) -> None:
        # Hook point for a real mailer. The route exists now; production can wire email delivery here.
        return None
