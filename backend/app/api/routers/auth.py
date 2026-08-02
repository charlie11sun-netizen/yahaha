from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordRequestForm
from fastapi_users import exceptions
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.api.deps import get_current_user, rate_limit
from app.core.config import settings
from app.api.user_auth import (
    UserManager,
    auth_backend,
    clear_session_cookie,
    create_user_token,
    fastapi_users,
    get_user_manager,
    set_session_cookie,
)
from app.db.session import get_db
from app.models import OAuthAccount, User
from app.schemas import (
    AuthOut,
    ChangePasswordIn,
    FastAPIUserCreate,
    FastAPIUserRead,
    FastAPIUserUpdate,
    LoginIn,
    OAuthDemoOut,
    OkOut,
    ProfileUpdateIn,
    RegisterIn,
    UserOut,
)
from app.services.serialize import user_out

router = APIRouter(prefix="/auth", tags=["auth"])


def _initial(name: str) -> str:
    return (name.strip()[:1] or "?").upper()


async def _auth_response(user: User, **extra) -> JSONResponse:
    token = await create_user_token(user)
    response = JSONResponse({"user": user_out(user), **extra})
    return set_session_cookie(response, token)


@router.post(
    "/register",
    response_model=AuthOut,
    response_model_exclude_unset=True,
    dependencies=[Depends(rate_limit(10, 60, "register"))],
)
async def register(
    body: RegisterIn,
    request: Request,
    user_manager: UserManager = Depends(get_user_manager),
):
    try:
        user = await user_manager.create(
            FastAPIUserCreate(
                email=body.email,
                password=body.password,
                display_name=body.display_name,
            ),
            safe=True,
            request=request,
        )
    except exceptions.UserAlreadyExists as exc:
        raise HTTPException(status_code=409, detail="Email already registered") from exc
    except exceptions.InvalidPasswordException as exc:
        raise HTTPException(status_code=422, detail=exc.reason) from exc
    return await _auth_response(user)


@router.post(
    "/login",
    response_model=AuthOut,
    response_model_exclude_unset=True,
    dependencies=[Depends(rate_limit(10, 60, "login"))],
)
async def login(
    body: LoginIn,
    user_manager: UserManager = Depends(get_user_manager),
):
    credentials = OAuth2PasswordRequestForm(username=body.email, password=body.password)
    user = await user_manager.authenticate(credentials)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is disabled")
    return await _auth_response(user)


@router.get("/me", response_model=UserOut, response_model_exclude_unset=True)
def me(user: User = Depends(get_current_user)):
    return user_out(user)


@router.patch("/me", response_model=UserOut, response_model_exclude_unset=True)
async def update_me(
    body: ProfileUpdateIn,
    request: Request,
    user: User = Depends(get_current_user),
    user_manager: UserManager = Depends(get_user_manager),
):
    update_data = {}
    if body.email is not None:
        update_data["email"] = body.email
    if body.display_name is not None:
        update_data["display_name"] = body.display_name
    if body.avatar is not None:
        update_data["avatar"] = body.avatar
    try:
        updated = await user_manager.update(
            FastAPIUserUpdate(**update_data),
            user,
            safe=True,
            request=request,
        )
    except exceptions.UserAlreadyExists as exc:
        raise HTTPException(status_code=409, detail="Email already in use") from exc
    except exceptions.InvalidPasswordException as exc:
        raise HTTPException(status_code=422, detail=exc.reason) from exc
    return user_out(updated)


@router.post(
    "/change-password",
    response_model=OkOut,
    response_model_exclude_unset=True,
    dependencies=[Depends(rate_limit(10, 60, "chpw"))],
)
async def change_password(
    body: ChangePasswordIn,
    request: Request,
    user: User = Depends(get_current_user),
    user_manager: UserManager = Depends(get_user_manager),
):
    if user.hashed_password:
        verified, _ = await run_in_threadpool(
            user_manager.password_helper.verify_and_update,
            body.current_password,
            user.hashed_password,
        )
        if not verified:
            raise HTTPException(status_code=400, detail="Current password is incorrect")
    try:
        await user_manager.update(
            FastAPIUserUpdate(password=body.new_password),
            user,
            safe=True,
            request=request,
        )
    except exceptions.InvalidPasswordException as exc:
        raise HTTPException(status_code=422, detail=exc.reason) from exc
    return {"ok": True}


@router.delete("/me", response_model=OkOut, response_model_exclude_unset=True)
async def delete_me(
    request: Request,
    user: User = Depends(get_current_user),
    user_manager: UserManager = Depends(get_user_manager),
):
    await user_manager.delete(user, request=request)
    return clear_session_cookie(JSONResponse({"ok": True}))


@router.post("/logout", response_model=OkOut, response_model_exclude_unset=True)
def logout():
    return clear_session_cookie(JSONResponse({"ok": True}))


@router.post("/oauth/{provider}/demo", response_model=OAuthDemoOut, response_model_exclude_unset=True)
async def oauth_demo(provider: str, db: Session = Depends(get_db)):
    """Explicitly enabled local-only OAuth demo using shared identities."""
    if not settings.ENABLE_OAUTH_DEMO:
        raise HTTPException(status_code=404, detail="OAuth demo is disabled")
    if provider not in ("google", "github"):
        raise HTTPException(status_code=404, detail="Unknown provider")
    name = "Ada Lovelace" if provider == "google" else "octocat"
    email = f"demo@{provider}.com"
    def get_or_create_demo_user():
        user = db.query(User).filter(User.email == email).first()
        if not user:
            try:
                user = User(email=email, display_name=name, avatar_initial=_initial(name), is_verified=True)
                db.add(user)
                db.flush()
                db.add(
                    OAuthAccount(
                        user_id=user.id,
                        provider=provider,
                        provider_account_id=email,
                        account_email=email,
                    )
                )
                db.commit()
                db.refresh(user)
            except Exception:
                db.rollback()
                raise
        return user

    user = await run_in_threadpool(get_or_create_demo_user)
    return await _auth_response(user, mock=True)


router.include_router(fastapi_users.get_auth_router(auth_backend), prefix="/session", tags=["auth"])
router.include_router(
    fastapi_users.get_register_router(FastAPIUserRead, FastAPIUserCreate),
    prefix="/users",
    tags=["auth"],
)
router.include_router(
    fastapi_users.get_reset_password_router(),
    prefix="/users",
    tags=["auth"],
)
router.include_router(
    fastapi_users.get_verify_router(FastAPIUserRead),
    prefix="/users",
    tags=["auth"],
)
router.include_router(
    fastapi_users.get_users_router(FastAPIUserRead, FastAPIUserUpdate),
    prefix="/users",
    tags=["auth"],
)
