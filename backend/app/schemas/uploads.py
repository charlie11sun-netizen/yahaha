"""上传域。"""
from pydantic import BaseModel


class UploadedAssetOut(BaseModel):
    id: str
    name: str
    kind: str
    size: int
    scan_status: str | None = None
    url: str | None = None


class UploadOut(BaseModel):
    assets: list[UploadedAssetOut]
