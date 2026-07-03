import datetime as dt
import hashlib

import bcrypt
import jwt

from app.core.config import settings


_BCRYPT_SHA256_PREFIX = "bcrypt-sha256$"


def _password_digest(password: str) -> bytes:
    """Keep bcrypt input fixed-size without making 72-byte prefixes collide."""
    return hashlib.sha256(password.encode("utf-8")).digest()


def hash_password(password: str) -> str:
    hashed = bcrypt.hashpw(_password_digest(password), bcrypt.gensalt()).decode("utf-8")
    return _BCRYPT_SHA256_PREFIX + hashed


def verify_password(password: str, password_hash: str) -> bool:
    try:
        if password_hash.startswith(_BCRYPT_SHA256_PREFIX):
            encoded_hash = password_hash.removeprefix(_BCRYPT_SHA256_PREFIX).encode("utf-8")
            return bcrypt.checkpw(_password_digest(password), encoded_hash)
        # Backward compatibility for hashes created before bcrypt-sha256 was introduced.
        return bcrypt.checkpw(password.encode("utf-8")[:72], password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def password_hash_needs_upgrade(password_hash: str) -> bool:
    return not password_hash.startswith(_BCRYPT_SHA256_PREFIX)


def create_access_token(subject: str) -> str:
    now = dt.datetime.now(dt.timezone.utc)
    payload = {
        "sub": subject,
        "iat": now,
        "exp": now + dt.timedelta(minutes=settings.JWT_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> str | None:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        return payload.get("sub")
    except jwt.PyJWTError:
        return None
