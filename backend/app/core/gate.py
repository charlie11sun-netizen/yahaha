"""Site access gate — backend half of the front-door password.

When SITE_PASSWORD is set, the API requires a matching X-Gate-Token header
(see the site_gate middleware in app.main). The token must be byte-identical to
the one the web front-end computes, so the hashing here mirrors frontend/lib/gate.ts:
``sha256("gameweave-gate:v1:" + password)`` over the trimmed password.
"""
import hashlib
import hmac

from app.core.config import settings


def _password() -> str:
    return settings.SITE_PASSWORD.strip()


def gate_enabled() -> bool:
    return bool(_password())


def public_browse_enabled() -> bool:
    return bool(settings.GATE_PUBLIC_BROWSE)


def public_browse_request(method: str, path: str) -> bool:
    if not public_browse_enabled():
        return False
    method = method.upper()
    if path in {"/health", "/health/ready", "/stats", "/tags"} and method == "GET":
        return True
    if path == "/games" and method == "GET":
        return True
    if path.startswith("/games/") and method == "GET":
        return True
    if path.endswith("/play") and path.startswith("/games/") and method == "POST":
        return True
    if path.endswith("/score") and path.startswith("/games/") and method == "POST":
        return True
    return False


def _token(password: str) -> str:
    return hashlib.sha256(f"gameweave-gate:v1:{password}".encode()).hexdigest()


def expected_token() -> str:
    return _token(_password())


def verify_gate_token(presented: str | None) -> bool:
    """Constant-time check of a presented X-Gate-Token against the expected one."""
    if not presented:
        return False
    return hmac.compare_digest(presented, expected_token())
