from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import Asset
from app.models.common import AssetKind, gen_uuid
from app.storage import s3

router = APIRouter(prefix="/uploads", tags=["uploads"])

MAX_FILES = 6


def _kind(content_type: str) -> str:
    if content_type.startswith("image"):
        return AssetKind.IMAGE
    if content_type.startswith("video"):
        return AssetKind.VIDEO
    return AssetKind.FILE


@router.post("")
async def upload(
    files: list[UploadFile] = File(...),
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    out = []
    for f in files[:MAX_FILES]:
        data = await f.read()
        asset_id = gen_uuid()
        content_type = f.content_type or "application/octet-stream"
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
