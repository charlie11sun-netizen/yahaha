"""真实 OAuth 授权码流程（Google / GitHub）。

配置了对应 CLIENT_ID/SECRET 即启用；否则前端回退到 /auth/oauth/{provider}/demo。
流程：/start 跳转授权页 → /callback 用 code 换 token、取 profile、
upsert User + OAuthAccount、签发本站 JWT，最后重定向回前端 /login?token=...
"""
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import create_access_token
from app.db.session import get_db
from app.models import OAuthAccount, User

router = APIRouter(prefix="/auth", tags=["oauth"])

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


@router.get("/oauth/providers")
def oauth_providers():
    """前端据此决定按钮走真实流程还是 demo。"""
    return {p: _enabled(p) for p in _PROVIDERS}


@router.get("/oauth/{provider}/start")
def oauth_start(provider: str):
    if provider not in _PROVIDERS:
        raise HTTPException(status_code=404, detail="Unknown provider")
    if not _enabled(provider):
        raise HTTPException(status_code=404, detail="Provider not configured")
    cid, _ = _creds(provider)
    state = jwt.encode({"p": provider}, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    params = {
        "client_id": cid,
        "redirect_uri": _redirect_uri(provider),
        "response_type": "code",
        "scope": _PROVIDERS[provider]["scope"],
        "state": state,
    }
    return RedirectResponse(f"{_PROVIDERS[provider]['authorize']}?{urlencode(params)}")


def _fetch_profile(provider: str, access_token: str) -> tuple[str, str | None, str]:
    cfg = _PROVIDERS[provider]
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
    prof = httpx.get(cfg["userinfo"], headers=headers, timeout=15).json()
    if provider == "google":
        return str(prof.get("sub") or ""), prof.get("email"), prof.get("name") or "Google User"
    account_id = str(prof.get("id") or "")
    email = prof.get("email")
    name = prof.get("name") or prof.get("login") or "GitHub User"
    if not email:
        emails = httpx.get("https://api.github.com/user/emails", headers=headers, timeout=15).json()
        if isinstance(emails, list) and emails:
            primary = next((e for e in emails if e.get("primary")), emails[0])
            email = primary.get("email")
    return account_id, email, name


@router.get("/oauth/{provider}/callback")
def oauth_callback(provider: str, code: str = "", state: str = "", db: Session = Depends(get_db)):
    if not _enabled(provider):
        raise HTTPException(status_code=404, detail="Provider not configured")
    try:
        jwt.decode(state, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except jwt.PyJWTError as exc:
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

    token = create_access_token(user.id)
    return RedirectResponse(f"{settings.FRONTEND_BASE_URL}/login?token={token}")
