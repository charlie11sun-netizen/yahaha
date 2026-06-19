"""请求体 Schema（响应统一用 services/serialize.py 输出 dict）。"""
from pydantic import BaseModel, EmailStr, Field


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


class ChangePasswordIn(BaseModel):
    current_password: str = ""
    new_password: str = Field(min_length=6)


class GameUpdateIn(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    summary: str | None = Field(default=None, max_length=2000)
    tags: list[str] | None = None


class TaskCreateIn(BaseModel):
    idea: str = Field(min_length=1)
    asset_ids: list[str] = []
