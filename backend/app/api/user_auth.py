"""FastAPI Users composition root.

Authentication transport and dependency wiring live at the API boundary so the
core user model does not depend on application services or object storage.
"""

from fastapi_users import BaseUserManager, FastAPIUsers, exceptions
from fastapi_users.authentication import AuthenticationBackend, BearerTransport, JWTStrategy

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


__all__ = [
    "UserManager",
    "auth_backend",
    "create_user_token",
    "current_user_dependency",
    "fastapi_users",
    "get_user_manager",
    "optional_user_dependency",
]
