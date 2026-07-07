import base64
import hashlib
import hmac
import json
import time
from urllib.parse import quote, urlencode

from app.core.config import settings


GAME_FILE_TOKEN_SECONDS = 3600


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def normalize_game_file_path(path: str) -> str:
    value = str(path or "").replace("\\", "/").lstrip("/")
    parts = [part for part in value.split("/") if part]
    if not parts or any(part in {".", ".."} for part in parts):
        raise ValueError("invalid game file path")
    return "/".join(parts)


def _api_base() -> str:
    return (settings.OAUTH_REDIRECT_BASE or "http://localhost:8000").rstrip("/")


def game_manifest_url(game_id: str, version: str | None = None) -> str:
    path = f"{_api_base()}/games/{quote(game_id, safe='')}/manifest"
    if version:
        return f"{path}?{urlencode({'version': version})}"
    return path


def game_file_token(game_id: str, version: str, *, expires_seconds: int = GAME_FILE_TOKEN_SECONDS) -> str:
    payload = {
        "game_id": game_id,
        "version": version,
        "exp": int(time.time()) + max(1, int(expires_seconds)),
    }
    raw_payload = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    encoded_payload = _b64encode(raw_payload)
    secret = settings.JWT_SECRET.encode("utf-8")
    signature = hmac.new(secret, encoded_payload.encode("ascii"), hashlib.sha256).digest()
    return f"{encoded_payload}.{_b64encode(signature)}"


def verify_game_file_token(token: str, game_id: str, version: str) -> bool:
    try:
        encoded_payload, encoded_signature = token.split(".", 1)
        expected = hmac.new(
            settings.JWT_SECRET.encode("utf-8"),
            encoded_payload.encode("ascii"),
            hashlib.sha256,
        ).digest()
        actual = _b64decode(encoded_signature)
        if not hmac.compare_digest(expected, actual):
            return False
        payload = json.loads(_b64decode(encoded_payload))
    except Exception:  # noqa: BLE001
        return False
    return (
        payload.get("game_id") == game_id
        and payload.get("version") == version
        and int(payload.get("exp") or 0) >= int(time.time())
    )


def game_file_url(game_id: str, version: str, path: str, *, token: str | None = None) -> str:
    clean_path = normalize_game_file_path(path)
    file_token = token or game_file_token(game_id, version)
    return (
        f"{_api_base()}/games/{quote(game_id, safe='')}/files/"
        f"{quote(file_token, safe='')}/{quote(version, safe='')}/{quote(clean_path, safe='/')}"
    )
