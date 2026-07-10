"""真实 OAuth 授权码流程（Google / GitHub）。

配置了对应 CLIENT_ID/SECRET 即启用；否则前端回退到 /auth/oauth/{provider}/demo。
流程：/start 跳转授权页 → /callback 用 code 换 token、取 profile、
upsert User + OAuthAccount、签发 HttpOnly Cookie 会话，最后重定向回前端。
"""
import datetime as dt
import hmac
import secrets
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.api.user_auth import create_user_token_sync, set_session_cookie
from app.core.config import settings
from app.db.session import get_db
from app.models import OAuthAccount, User
from app.schemas import OAuthProvidersOut

router = APIRouter(prefix="/auth", tags=["oauth"])
_STATE_COOKIE = "gameweave_oauth_state"
_STATE_TTL_SECONDS = 600

_PROVIDERS = {
    "google": {
        "authorize": "https://accounts.google.com/o/oauth2/v2/auth",
        "token": "https://oauth2.googleapis.com/token",
        "userinfo": "https://openidconnect.googleapis.com/v1/userinfo",
        "scope": "openid email profile",
    },
    "github": {
        "authorize": "https://github.com/login/oauth/authorize",
        "token": "https://github.com/login/oauth/access_token",
        "userinfo": "https://api.github.com/user",
        "scope": "read:user user:email",
    },
}


def _creds(provider: str) -> tuple[str, str]:
    if provider == "google":
        return settings.GOOGLE_CLIENT_ID, settings.GOOGLE_CLIENT_SECRET
    if provider == "github":
        return settings.GITHUB_CLIENT_ID, settings.GITHUB_CLIENT_SECRET
    return "", ""


def _enabled(provider: str) -> bool:
    cid, secret = _creds(provider)
    return bool(provider in _PROVIDERS and cid and secret)


def _initial(name: str) -> str:
    return (name.strip()[:1] or "?").upper()


def _redirect_uri(provider: str) -> str:
    return f"{settings.OAUTH_REDIRECT_BASE}/auth/oauth/{provider}/callback"


@router.get("/oauth/providers", response_model=OAuthProvidersOut, response_model_exclude_unset=True)
def oauth_providers():
    """前端据此决定按钮走真实流程还是 demo。"""
    return {**{p: _enabled(p) for p in _PROVIDERS}, "_demo": settings.ENABLE_OAUTH_DEMO}


@router.get("/oauth/{provider}/start")
def oauth_start(provider: str):
    if provider not in _PROVIDERS:
        raise HTTPException(status_code=404, detail="Unknown provider")
    if not _enabled(provider):
        raise HTTPException(status_code=404, detail="Provider not configured")
    cid, _ = _creds(provider)
    nonce = secrets.token_urlsafe(32)
    now = dt.datetime.now(dt.timezone.utc)
    state = jwt.encode(
        {
            "p": provider,
            "n": nonce,
            "iat": now,
            "exp": now + dt.timedelta(seconds=_STATE_TTL_SECONDS),
        },
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )
    params = {
        "client_id": cid,
        "redirect_uri": _redirect_uri(provider),
        "response_type": "code",
        "scope": _PROVIDERS[provider]["scope"],
        "state": state,
    }
    response = RedirectResponse(f"{_PROVIDERS[provider]['authorize']}?{urlencode(params)}")
    response.set_cookie(
        _STATE_COOKIE,
        nonce,
        max_age=_STATE_TTL_SECONDS,
        httponly=True,
        secure=_redirect_uri(provider).startswith("https://"),
        samesite="lax",
        path="/auth/oauth/",
    )
    return response


def _fetch_profile(provider: str, access_token: str) -> tuple[str, str | None, str]:
    cfg = _PROVIDERS[provider]
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
    prof = httpx.get(cfg["userinfo"], headers=headers, timeout=15).json()
    if provider == "google":
        email = prof.get("email") if prof.get("email_verified") is True else None
        return str(prof.get("sub") or ""), email, prof.get("name") or "Google User"
    account_id = str(prof.get("id") or "")
    name = prof.get("name") or prof.get("login") or "GitHub User"
    emails = httpx.get("https://api.github.com/user/emails", headers=headers, timeout=15).json()
    verified = [e for e in emails if e.get("verified") and e.get("email")] if isinstance(emails, list) else []
    primary = next((e for e in verified if e.get("primary")), verified[0] if verified else None)
    email = primary.get("email") if primary else None
    return account_id, email, name


@router.get("/oauth/{provider}/callback")
def oauth_callback(
    provider: str,
    request: Request,
    code: str = "",
    state: str = "",
    db: Session = Depends(get_db),
):
    if not _enabled(provider):
        raise HTTPException(status_code=404, detail="Provider not configured")
    try:
        claims = jwt.decode(
            state,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
            options={"require": ["exp", "iat"]},
        )
        expected_nonce = request.cookies.get(_STATE_COOKIE) or ""
        actual_nonce = str(claims.get("n") or "")
        if claims.get("p") != provider or not expected_nonce or not hmac.compare_digest(actual_nonce, expected_nonce):
            raise ValueError("OAuth state is not bound to this browser")
    except (jwt.PyJWTError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Invalid OAuth state") from exc

    cid, secret = _creds(provider)
    token_resp = httpx.post(
        _PROVIDERS[provider]["token"],
        data={
            "client_id": cid,
            "client_secret": secret,
            "code": code,
            "redirect_uri": _redirect_uri(provider),
            "grant_type": "authorization_code",
        },
        headers={"Accept": "application/json"},
        timeout=15,
    )
    access_token = token_resp.json().get("access_token")
    if not access_token:
        raise HTTPException(status_code=400, detail="OAuth token exchange failed")

    account_id, email, name = _fetch_profile(provider, access_token)
    if not account_id or not email:
        raise HTTPException(status_code=400, detail="OAuth profile incomplete")

    acct = (
        db.query(OAuthAccount)
        .filter_by(provider=provider, provider_account_id=account_id)
        .first()
    )
    if acct:
        user = db.get(User, acct.user_id)
    else:
        user = db.query(User).filter(User.email == email).first()
        if not user:
            user = User(email=email, display_name=name, avatar_initial=_initial(name))
            db.add(user)
            db.flush()
        db.add(OAuthAccount(
            user_id=user.id, provider=provider,
            provider_account_id=account_id, account_email=email,
        ))
        db.commit()
        db.refresh(user)

    if not user.is_active:
        # 与密码登录同一条规则：禁用账号不得经 OAuth 换取新 token
        raise HTTPException(status_code=403, detail="Account is disabled")

    token = create_user_token_sync(user)
    response = RedirectResponse(f"{settings.FRONTEND_BASE_URL}/login?oauth=success")
    set_session_cookie(response, token)
    response.delete_cookie(_STATE_COOKIE, path="/auth/oauth/")
    return response
