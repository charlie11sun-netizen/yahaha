from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, rate_limit
from app.core.security import create_access_token, hash_password, verify_password
from app.db.session import get_db
from app.models import OAuthAccount, User
from app.schemas import ChangePasswordIn, LoginIn, ProfileUpdateIn, RegisterIn
from app.services.serialize import user_out

router = APIRouter(prefix="/auth", tags=["auth"])


def _initial(name: str) -> str:
    return (name.strip()[:1] or "?").upper()


@router.post("/register", dependencies=[Depends(rate_limit(10, 60, "register"))])
def register(body: RegisterIn, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == body.email).first():
        raise HTTPException(status_code=409, detail="Email already registered")
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


@router.post("/login", dependencies=[Depends(rate_limit(10, 60, "login"))])
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == body.email).first()
    if not user or not user.password_hash or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is disabled")
    return {"token": create_access_token(user.id), "user": user_out(user)}


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return user_out(user)


@router.patch("/me")
def update_me(body: ProfileUpdateIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if body.display_name is not None:
        user.display_name = body.display_name.strip()
        user.avatar_initial = _initial(user.display_name)
    if body.email is not None and body.email != user.email:
        if db.query(User).filter(User.email == body.email, User.id != user.id).first():
            raise HTTPException(status_code=409, detail="Email already in use")
        user.email = body.email
    db.commit()
    db.refresh(user)
    return user_out(user)


@router.post("/change-password", dependencies=[Depends(rate_limit(10, 60, "chpw"))])
def change_password(body: ChangePasswordIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.password_hash and not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    user.password_hash = hash_password(body.new_password)
    db.commit()
    return {"ok": True}


@router.delete("/me")
def delete_me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.delete(user)
    db.commit()
    return {"ok": True}


@router.post("/logout")
def logout(_user: User = Depends(get_current_user)):
    # 无状态 JWT：前端丢弃 token 即登出
    return {"ok": True}


@router.post("/oauth/{provider}/demo")
def oauth_demo(provider: str, db: Session = Depends(get_db)):
    """Mock OAuth（demo）。真实接入设计见 docs/数据模型与接口.md。"""
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
