"""跨域通用响应体。"""
from pydantic import BaseModel


class OkOut(BaseModel):
    ok: bool
