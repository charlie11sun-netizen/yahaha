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


def _token(password: str) -> str:
    return hashlib.sha256(f"gameweave-gate:v1:{password}".encode()).hexdigest()


def expected_token() -> str:
    return _token(_password())


def verify_gate_token(presented: str | None) -> bool:
    """Constant-time check of a presented X-Gate-Token against the expected one."""
    if not presented:
        return False
    return hmac.compare_digest(presented, expected_token())
