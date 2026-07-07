from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, rate_limit
from app.core.config import settings
from app.core.security import create_access_token, hash_password, password_hash_needs_upgrade, verify_password
from app.db.session import get_db
from app.models import OAuthAccount, User
from app.schemas import (
    AuthOut,
    ChangePasswordIn,
    LoginIn,
    OAuthDemoOut,
    OkOut,
    ProfileUpdateIn,
    RegisterIn,
    UserOut,
)
from app.services import content_safety
from app.services.serialize import user_out

router = APIRouter(prefix="/auth", tags=["auth"])


def _initial(name: str) -> str:
    return (name.strip()[:1] or "?").upper()


@router.post(
    "/register",
    response_model=AuthOut,
    response_model_exclude_unset=True,
    dependencies=[Depends(rate_limit(10, 60, "register"))],
)
def register(body: RegisterIn, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == body.email).first():
        raise HTTPException(status_code=409, detail="Email already registered")
    content_safety.ensure_allowed(
        db,
        text=body.display_name,
        surface="auth.register.display_name",
    )
    user = User(
        email=body.email,
        password_hash=hash_password(body.password),
        display_name=body.display_name,
        avatar_initial=_initial(body.display_name),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"token": create_access_token(user.id), "user": user_out(user)}


@router.post(
    "/login",
    response_model=AuthOut,
    response_model_exclude_unset=True,
    dependencies=[Depends(rate_limit(10, 60, "login"))],
)
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == body.email).first()
    if not user or not user.password_hash or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is disabled")
    if password_hash_needs_upgrade(user.password_hash):
        user.password_hash = hash_password(body.password)
        db.commit()
    return {"token": create_access_token(user.id), "user": user_out(user)}


@router.get("/me", response_model=UserOut, response_model_exclude_unset=True)
def me(user: User = Depends(get_current_user)):
    return user_out(user)


@router.patch("/me", response_model=UserOut, response_model_exclude_unset=True)
def update_me(body: ProfileUpdateIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if body.display_name is not None:
        content_safety.ensure_allowed(
            db,
            text=body.display_name,
            surface="user.display_name",
            user_id=user.id,
            object_id=user.id,
        )
    if body.avatar is not None and body.avatar.strip():
        content_safety.ensure_allowed(
            db,
            text=body.avatar,
            surface="user.avatar",
            user_id=user.id,
            object_id=user.id,
        )
    if body.display_name is not None:
        user.display_name = body.display_name.strip()
        user.avatar_initial = _initial(user.display_name)
    if body.email is not None and body.email != user.email:
        if db.query(User).filter(User.email == body.email, User.id != user.id).first():
            raise HTTPException(status_code=409, detail="Email already in use")
        user.email = body.email
    if body.avatar is not None and body.avatar.strip():
        user.avatar_initial = body.avatar.strip()[:4]
    db.commit()
    db.refresh(user)
    return user_out(user)


@router.post(
    "/change-password",
    response_model=OkOut,
    response_model_exclude_unset=True,
    dependencies=[Depends(rate_limit(10, 60, "chpw"))],
)
def change_password(body: ChangePasswordIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.password_hash and not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    user.password_hash = hash_password(body.new_password)
    db.commit()
    return {"ok": True}


@router.delete("/me", response_model=OkOut, response_model_exclude_unset=True)
def delete_me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.models import Game
    from app.storage import s3

    # 先记下要清的对象存储前缀（游戏 bundle 公网可读、上传件永久滞留），DB 级联删除后清理
    game_ids = [gid for (gid,) in db.query(Game.id).filter(Game.author_id == user.id)]
    uid = user.id
    db.delete(user)
    db.commit()
    try:
        for gid in game_ids:
            s3.delete_prefix(f"games/{gid}/")
        s3.delete_prefix(f"uploads/{uid}/")
    except Exception:  # noqa: BLE001  尽力清理，OSS 不可用不阻塞删号
        pass
    return {"ok": True}


@router.post("/logout", response_model=OkOut, response_model_exclude_unset=True)
def logout(_user: User = Depends(get_current_user)):
    # 无状态 JWT：前端丢弃 token 即登出
    return {"ok": True}


@router.post("/oauth/{provider}/demo", response_model=OAuthDemoOut, response_model_exclude_unset=True)
def oauth_demo(provider: str, db: Session = Depends(get_db)):
    """Explicitly enabled local-only OAuth demo using shared identities."""
    if not settings.ENABLE_OAUTH_DEMO:
        raise HTTPException(status_code=404, detail="OAuth demo is disabled")
    if provider not in ("google", "github"):
        raise HTTPException(status_code=404, detail="Unknown provider")
    name = "Ada Lovelace" if provider == "google" else "octocat"
    email = f"demo@{provider}.com"
    user = db.query(User).filter(User.email == email).first()
    if not user:
        user = User(email=email, display_name=name, avatar_initial=_initial(name))
        db.add(user)
        db.flush()
        db.add(OAuthAccount(
            user_id=user.id, provider=provider, provider_account_id=email, account_email=email,
        ))
        db.commit()
        db.refresh(user)
    return {"token": create_access_token(user.id), "user": user_out(user), "mock": True}
