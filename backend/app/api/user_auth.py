"""FastAPI Users composition root.

Authentication transport and dependency wiring live at the API boundary so the
core user model does not depend on application services or object storage.
"""

from fastapi import Response
from fastapi_users import BaseUserManager, FastAPIUsers, exceptions
from fastapi_users.authentication import AuthenticationBackend, CookieTransport, JWTStrategy
from fastapi_users.jwt import generate_jwt

from app.core.config import settings
from app.core.security import FASTAPI_USERS_TOKEN_AUDIENCE, decode_token
from app.models import User
from app.services.user_accounts import UserManager, get_user_manager


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


cookie_transport = CookieTransport(
    cookie_name=settings.AUTH_COOKIE_NAME,
    cookie_max_age=settings.JWT_EXPIRE_MINUTES * 60,
    cookie_path="/",
    cookie_domain=settings.AUTH_COOKIE_DOMAIN or None,
    cookie_secure=settings.AUTH_COOKIE_SECURE,
    cookie_httponly=True,
    cookie_samesite=settings.AUTH_COOKIE_SAMESITE,
)
auth_backend = AuthenticationBackend(
    name="cookie",
    transport=cookie_transport,
    get_strategy=get_jwt_strategy,
)
fastapi_users = FastAPIUsers[User, str](get_user_manager, [auth_backend])
current_user_dependency = fastapi_users.current_user(active=False)
optional_user_dependency = fastapi_users.current_user(active=False, optional=True)


async def create_user_token(user: User) -> str:
    return create_user_token_sync(user)


def create_user_token_sync(user: User) -> str:
    return generate_jwt(
        {"sub": str(user.id), "aud": FASTAPI_USERS_TOKEN_AUDIENCE},
        settings.JWT_SECRET,
        settings.JWT_EXPIRE_MINUTES * 60,
        algorithm=settings.JWT_ALGORITHM,
    )


def set_session_cookie(response: Response, token: str) -> Response:
    response.set_cookie(
        settings.AUTH_COOKIE_NAME,
        token,
        max_age=settings.JWT_EXPIRE_MINUTES * 60,
        path="/",
        domain=settings.AUTH_COOKIE_DOMAIN or None,
        secure=settings.AUTH_COOKIE_SECURE,
        httponly=True,
        samesite=settings.AUTH_COOKIE_SAMESITE,
    )
    return response


def clear_session_cookie(response: Response) -> Response:
    response.set_cookie(
        settings.AUTH_COOKIE_NAME,
        "",
        max_age=0,
        path="/",
        domain=settings.AUTH_COOKIE_DOMAIN or None,
        secure=settings.AUTH_COOKIE_SECURE,
        httponly=True,
        samesite=settings.AUTH_COOKIE_SAMESITE,
    )
    return response


__all__ = [
    "UserManager",
    "auth_backend",
    "clear_session_cookie",
    "cookie_transport",
    "create_user_token",
    "create_user_token_sync",
    "current_user_dependency",
    "fastapi_users",
    "get_user_manager",
    "optional_user_dependency",
    "set_session_cookie",
]
