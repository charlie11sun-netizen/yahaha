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
    display_name: str = Field(min_length=1, max_length=120)


class TaskCreateIn(BaseModel):
    idea: str = Field(min_length=1)
    asset_ids: list[str] = []
