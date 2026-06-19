from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, rate_limit
from app.db.session import get_db
from app.models import Asset
from app.models.common import AssetKind, gen_uuid
from app.storage import s3

router = APIRouter(prefix="/uploads", tags=["uploads"])

MAX_FILES = 6
MAX_FILE_BYTES = 10 * 1024 * 1024      # 单文件 10MB
MAX_TOTAL_BYTES = 40 * 1024 * 1024     # 单次合计 40MB
_ALLOWED_PREFIXES = ("image/", "video/", "audio/")
_ALLOWED_EXACT = {"application/pdf", "application/json", "application/zip", "text/plain"}


def _allowed(content_type: str) -> bool:
    return content_type.startswith(_ALLOWED_PREFIXES) or content_type in _ALLOWED_EXACT


def _kind(content_type: str) -> str:
    if content_type.startswith("image"):
        return AssetKind.IMAGE
    if content_type.startswith("video"):
        return AssetKind.VIDEO
    return AssetKind.FILE


@router.post("", dependencies=[Depends(rate_limit(60, 3600, "upload"))])
async def upload(
    files: list[UploadFile] = File(...),
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    out = []
    total = 0
    for f in files[:MAX_FILES]:
        data = await f.read()
        content_type = f.content_type or "application/octet-stream"
        if not _allowed(content_type):
            raise HTTPException(status_code=415, detail=f"Unsupported file type: {content_type}")
        if len(data) > MAX_FILE_BYTES:
            raise HTTPException(status_code=413, detail=f"{f.filename or 'file'} exceeds 10MB limit")
        total += len(data)
        if total > MAX_TOTAL_BYTES:
            raise HTTPException(status_code=413, detail="Total upload exceeds 40MB limit")
        asset_id = gen_uuid()
        key = f"uploads/{user.id}/{asset_id}/{f.filename}"
        s3.put_object(key, data, content_type)
        asset = Asset(
            id=asset_id,
            owner_id=user.id,
            filename=f.filename or "file",
            content_type=content_type,
            kind=_kind(content_type),
            size_bytes=len(data),
            oss_key=key,
        )
        db.add(asset)
        out.append(asset)
    db.commit()
    return {
        "assets": [
            {
                "id": a.id,
                "name": a.filename,
                "kind": a.kind,
                "size": a.size_bytes,
                "url": s3.public_url(a.oss_key),
            }
            for a in out
        ]
    }
