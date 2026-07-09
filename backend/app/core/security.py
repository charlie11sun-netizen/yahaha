import datetime as dt
import hashlib
import secrets

import bcrypt
import jwt
from fastapi_users.jwt import decode_jwt, generate_jwt
from fastapi_users.password import PasswordHelper

from app.core.config import settings


_BCRYPT_SHA256_PREFIX = "bcrypt-sha256$"
FASTAPI_USERS_TOKEN_AUDIENCE = ["fastapi-users:auth"]
_password_helper = PasswordHelper()


def _password_digest(password: str) -> bytes:
    """Keep bcrypt input fixed-size without making 72-byte prefixes collide."""
    return hashlib.sha256(password.encode("utf-8")).digest()


def _is_legacy_hash(password_hash: str | None) -> bool:
    return bool(
        password_hash
        and (
            password_hash.startswith(_BCRYPT_SHA256_PREFIX)
            or password_hash.startswith("$2a$")
            or password_hash.startswith("$2b$")
            or password_hash.startswith("$2y$")
        )
    )


def _verify_legacy_password(password: str, password_hash: str) -> bool:
    try:
        if password_hash.startswith(_BCRYPT_SHA256_PREFIX):
            encoded_hash = password_hash.removeprefix(_BCRYPT_SHA256_PREFIX).encode("utf-8")
            return bcrypt.checkpw(_password_digest(password), encoded_hash)
        return bcrypt.checkpw(password.encode("utf-8")[:72], password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


class CompatiblePasswordHelper:
    """FastAPI Users password helper that upgrades legacy app hashes on login."""

    def verify_and_update(self, plain_password: str, hashed_password: str) -> tuple[bool, str | None]:
        if _is_legacy_hash(hashed_password):
            verified = _verify_legacy_password(plain_password, hashed_password)
            return verified, self.hash(plain_password) if verified else None
        return _password_helper.verify_and_update(plain_password, hashed_password)

    def hash(self, password: str) -> str:
        return _password_helper.hash(password)

    def generate(self) -> str:
        return secrets.token_urlsafe()


password_helper = CompatiblePasswordHelper()


def hash_password(password: str) -> str:
    return password_helper.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    verified, _ = password_helper.verify_and_update(password, password_hash)
    return verified


def password_hash_needs_upgrade(password_hash: str) -> bool:
    return _is_legacy_hash(password_hash)


def create_access_token(subject: str) -> str:
    return generate_jwt(
        {
            "sub": subject,
            "aud": FASTAPI_USERS_TOKEN_AUDIENCE,
        },
        settings.JWT_SECRET,
        lifetime_seconds=settings.JWT_EXPIRE_MINUTES * 60,
        algorithm=settings.JWT_ALGORITHM,
    )


def create_legacy_access_token(subject: str) -> str:
    """Create the pre-FastAPI-Users token shape for migration tests/tools."""
    now = dt.datetime.now(dt.timezone.utc)
    return jwt.encode(
        {
            "sub": subject,
            "iat": now,
            "exp": now + dt.timedelta(minutes=settings.JWT_EXPIRE_MINUTES),
        },
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )


def _decode_legacy_token(token: str) -> str | None:
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
            options={"verify_aud": False},
        )
        if payload.get("aud"):
            return None
        return payload.get("sub")
    except jwt.PyJWTError:
        return None


def decode_token(token: str) -> str | None:
    try:
        payload = decode_jwt(
            token,
            settings.JWT_SECRET,
            FASTAPI_USERS_TOKEN_AUDIENCE,
            algorithms=[settings.JWT_ALGORITHM],
        )
        return payload.get("sub")
    except jwt.PyJWTError:
        return _decode_legacy_token(token)
