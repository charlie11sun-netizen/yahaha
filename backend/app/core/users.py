from collections.abc import AsyncGenerator, Generator
from typing import Any

from fastapi import Depends, Request
from fastapi_users import BaseUserManager, FastAPIUsers, exceptions
from fastapi_users.authentication import AuthenticationBackend, BearerTransport, JWTStrategy
from fastapi_users.db import BaseUserDatabase
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import FASTAPI_USERS_TOKEN_AUDIENCE, decode_token, password_helper
from app.db.session import get_db
from app.models import Game, OAuthAccount, User
from app.services import content_safety
from app.storage import s3


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
        self._delete_cleanup: tuple[str, list[str]] | None = None

    def parse_id(self, value: Any) -> str:
        if isinstance(value, str) and value:
            return value
        raise exceptions.InvalidID()

    async def validate_password(self, password: str, user: User | Any) -> None:
        if len(password) < 6:
            raise exceptions.InvalidPasswordException(reason="Password should be at least 6 characters")

    async def create(self, user_create, safe: bool = False, request: Request | None = None) -> User:
        display_name = getattr(user_create, "display_name", None)
        if display_name:
            content_safety.ensure_allowed(
                self.user_db.session,
                text=display_name,
                surface="auth.register.display_name",
            )
        return await super().create(user_create, safe=safe, request=request)

    async def update(self, user_update, user: User, safe: bool = False, request: Request | None = None) -> User:
        display_name = getattr(user_update, "display_name", None)
        avatar = getattr(user_update, "avatar", None)
        if display_name is not None:
            content_safety.ensure_allowed(
                self.user_db.session,
                text=display_name,
                surface="user.display_name",
                user_id=user.id,
                object_id=user.id,
            )
        if avatar is not None and str(avatar).strip():
            content_safety.ensure_allowed(
                self.user_db.session,
                text=avatar,
                surface="user.avatar",
                user_id=user.id,
                object_id=user.id,
            )
        return await super().update(user_update, user, safe=safe, request=request)

    async def on_before_delete(self, user: User, request: Request | None = None) -> None:
        game_ids = [gid for (gid,) in self.user_db.session.query(Game.id).filter(Game.author_id == user.id)]
        self._delete_cleanup = (user.id, game_ids)

    async def on_after_delete(self, user: User, request: Request | None = None) -> None:
        if not self._delete_cleanup:
            return
        uid, game_ids = self._delete_cleanup
        try:
            for gid in game_ids:
                s3.delete_prefix(f"games/{gid}/")
            s3.delete_prefix(f"uploads/{uid}/")
        except Exception:  # noqa: BLE001
            pass

    async def on_after_forgot_password(self, user: User, token: str, request: Request | None = None) -> None:
        # Hook point for a real mailer. The route exists now; production can wire email delivery here.
        return None

    async def on_after_request_verify(self, user: User, token: str, request: Request | None = None) -> None:
        # Hook point for a real mailer. The route exists now; production can wire email delivery here.
        return None


async def get_user_manager(
    user_db: SyncSQLAlchemyUserDatabase = Depends(get_user_db),
) -> AsyncGenerator[UserManager, None]:
    yield UserManager(user_db)


class CompatibleJWTStrategy(JWTStrategy[User, str]):
    async def read_token(self, token: str | None, user_manager: BaseUserManager[User, str]) -> User | None:
        user = await super().read_token(token, user_manager)
        if user or token is None:
            return user
        user_id = decode_token(token)
        if not user_id:
            return None
        try:
            return await user_manager.get(user_manager.parse_id(user_id))
        except (exceptions.UserNotExists, exceptions.InvalidID):
            return None


def get_jwt_strategy() -> CompatibleJWTStrategy:
    return CompatibleJWTStrategy(
        secret=settings.JWT_SECRET,
        lifetime_seconds=settings.JWT_EXPIRE_MINUTES * 60,
        token_audience=FASTAPI_USERS_TOKEN_AUDIENCE,
        algorithm=settings.JWT_ALGORITHM,
    )


bearer_transport = BearerTransport(tokenUrl="/auth/jwt/login")
auth_backend = AuthenticationBackend(
    name="jwt",
    transport=bearer_transport,
    get_strategy=get_jwt_strategy,
)
fastapi_users = FastAPIUsers[User, str](get_user_manager, [auth_backend])
current_user_dependency = fastapi_users.current_user(active=False)
optional_user_dependency = fastapi_users.current_user(active=False, optional=True)


async def create_user_token(user: User) -> str:
    return await get_jwt_strategy().write_token(user)
