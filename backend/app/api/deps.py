import redis as redis_lib
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import decode_token
from app.core.telemetry import bind_context
from app.db.session import get_db
from app.models import User

bearer = HTTPBearer(auto_error=False)

_rl_redis: "redis_lib.Redis | None" = None


def _get_rl_redis() -> "redis_lib.Redis":
    global _rl_redis
    if _rl_redis is None:
        _rl_redis = redis_lib.Redis.from_url(settings.REDIS_URL)
    return _rl_redis


def rate_limit(limit: int, window: int, scope: str):
    """基于 Redis 的简单 IP 限流依赖工厂；Redis 不可用时放行(fail-open)。"""

    def _dep(request: Request) -> None:
        client = request.client.host if request.client else "anon"
        key = f"rl:{scope}:{client}"
        try:
            r = _get_rl_redis()
            count = r.incr(key)
            if count == 1:
                r.expire(key, window)
        except redis_lib.RedisError:
            return
        if count > limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests. Please slow down.",
            )

    return _dep


def _user_from_creds(creds: HTTPAuthorizationCredentials | None, db: Session) -> User | None:
    if not creds:
        return None
    uid = decode_token(creds.credentials)
    if not uid:
        return None
    return db.get(User, uid)


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    user = _user_from_creds(creds, db)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    # "禁用"必须对持旧 JWT 的会话全局生效，而不只在密码登录那一刻检查
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is disabled")
    bind_context(user_id=user.id)
    return user


def get_optional_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User | None:
    user = _user_from_creds(creds, db)
    return user if user and user.is_active else None
