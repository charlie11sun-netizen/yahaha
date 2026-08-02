"""身份域:注册/登录/资料/OAuth/关注。"""
from datetime import datetime

from fastapi_users import schemas as fastapi_users_schemas
from pydantic import BaseModel, ConfigDict, EmailStr, Field


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)
    display_name: str = Field(min_length=1, max_length=120)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class ProfileUpdateIn(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    email: EmailStr | None = None
    avatar: str | None = Field(default=None, max_length=8)


class ChangePasswordIn(BaseModel):
    current_password: str = ""
    new_password: str = Field(min_length=6)


class UserOut(BaseModel):
    id: str
    name: str
    email: EmailStr
    init: str
    created_at: str | None = None


class FastAPIUserRead(fastapi_users_schemas.BaseUser[str]):
    display_name: str
    avatar_initial: str
    name: str
    init: str
    created_at: datetime | None = None


class FastAPIUserCreate(fastapi_users_schemas.BaseUserCreate):
    display_name: str = Field(min_length=1, max_length=120)
    avatar: str | None = Field(default=None, max_length=8)


class FastAPIUserUpdate(fastapi_users_schemas.BaseUserUpdate):
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    avatar: str | None = Field(default=None, max_length=8)


class AuthOut(BaseModel):
    user: UserOut


class OAuthDemoOut(AuthOut):
    mock: bool


class OAuthProvidersOut(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    google: bool | None = None
    github: bool | None = None
    demo: bool = Field(alias="_demo")


class PublicUserProfileOut(BaseModel):
    id: str
    name: str
    init: str
    game_count: int
    total_plays: int
    followers: int
    following: int
    is_following: bool
    is_self: bool


class FollowOut(BaseModel):
    following: bool
