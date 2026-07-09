import redis as redis_lib
from fastapi import Depends, HTTPException, Request, status

from app.core.config import settings
from app.core.telemetry import bind_context
from app.core.users import current_user_dependency, optional_user_dependency
from app.models import User

_rl_redis: "redis_lib.Redis | None" = None


def _get_rl_redis() -> "redis_lib.Redis":
    global _rl_redis
    if _rl_redis is None:
        _rl_redis = redis_lib.Redis.from_url(settings.REDIS_URL)
    return _rl_redis


def rate_limit(limit: int, window: int, scope: str):
    """Redis-backed IP rate limiter dependency."""

    def _dep(request: Request) -> None:
        client = request.client.host if request.client else "anon"
        key = f"rl:{scope}:{client}"
        try:
            r = _get_rl_redis()
            count = r.incr(key)
            if count == 1:
                r.expire(key, window)
        except redis_lib.RedisError as exc:
            if settings.RATE_LIMIT_FAIL_OPEN:
                return
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="RATE_LIMIT_UNAVAILABLE",
            ) from exc
        if count > limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests. Please slow down.",
            )

    return _dep


def get_current_user(user: User | None = Depends(current_user_dependency)) -> User:
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is disabled")
    bind_context(user_id=user.id)
    return user


def get_optional_user(user: User | None = Depends(optional_user_dependency)) -> User | None:
    return user if user and user.is_active else None
