import re

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, rate_limit
from app.db.session import get_db
from app.models import Asset
from app.models.common import gen_uuid
from app.schemas import UploadOut
from app.services.upload_safety import (
    SafeUpload,
    UploadRejected,
    UploadScannerUnavailable,
    presigned_asset_url,
    sanitize_upload,
)
from app.storage import s3

router = APIRouter(prefix="/uploads", tags=["uploads"])

MAX_FILES = 6
MAX_FILE_BYTES = 10 * 1024 * 1024      # 单文件 10MB
MAX_TOTAL_BYTES = 40 * 1024 * 1024     # 单次合计 40MB
@router.post(
    "",
    response_model=UploadOut,
    response_model_exclude_unset=True,
    dependencies=[Depends(rate_limit(60, 3600, "upload"))],
)
async def upload(
    files: list[UploadFile] = File(...),
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if len(files) > MAX_FILES:
        raise HTTPException(status_code=413, detail=f"At most {MAX_FILES} files may be uploaded at once")

    prepared: list[SafeUpload] = []
    total = 0
    for f in files:
        data = await f.read(MAX_FILE_BYTES + 1)
        if len(data) > MAX_FILE_BYTES:
            raise HTTPException(status_code=413, detail=f"{f.filename or 'file'} exceeds 10MB limit")
        total += len(data)
        if total > MAX_TOTAL_BYTES:
            raise HTTPException(status_code=413, detail="Total upload exceeds 40MB limit")
        filename = re.split(r"[/\\]", f.filename or "file")[-1].strip()[:255] or "file"
        try:
            prepared.append(sanitize_upload(filename, data, f.content_type))
        except UploadScannerUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except UploadRejected as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    out = []
    uploaded_keys: list[str] = []
    try:
        for safe in prepared:
            asset_id = gen_uuid()
            key = f"uploads/{user.id}/{asset_id}/{safe.filename}"
            s3.put_object(key, safe.content, safe.content_type)
            uploaded_keys.append(key)
            asset = Asset(
                id=asset_id,
                owner_id=user.id,
                filename=safe.filename,
                content_type=safe.content_type,
                kind=safe.kind,
                size_bytes=len(safe.content),
                oss_key=key,
                scan_status=safe.scan_status,
            )
            db.add(asset)
            out.append(asset)
        db.commit()
    except Exception:
        # 第 N 个上传失败时 DB 会整体回滚，但前 N-1 个对象已在 OSS —— 回删防孤儿
        db.rollback()
        for key in uploaded_keys:
            try:
                s3.delete_prefix(key)
            except Exception:  # noqa: BLE001
                pass
        raise HTTPException(status_code=502, detail="Upload storage failed, please retry")
    return {
        "assets": [
            {
                "id": a.id,
                "name": a.filename,
                "kind": a.kind,
                "size": a.size_bytes,
                "scan_status": a.scan_status,
                "url": presigned_asset_url(a),
            }
            for a in out
        ]
    }
