from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass
from io import BytesIO

try:
    import filetype
except ImportError:  # pragma: no cover - requirements include filetype
    filetype = None
from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.config import settings
from app.models import Asset
from app.models.common import AssetKind
from app.storage import s3

MAX_IMAGE_DIMENSION = 8192
MAX_ZIP_ENTRIES = 100
MAX_ZIP_UNCOMPRESSED_BYTES = 100 * 1024 * 1024
MAX_ZIP_COMPRESSION_RATIO = 100

Image.MAX_IMAGE_PIXELS = MAX_IMAGE_DIMENSION * MAX_IMAGE_DIMENSION


class UploadRejected(ValueError):
    def __init__(self, detail: str, status_code: int = 415):
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


class UploadScannerUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class SafeUpload:
    filename: str
    content: bytes
    content_type: str
    kind: str
    scan_status: str


def _guess_mime(data: bytes) -> str | None:
    if filetype:
        kind = filetype.guess(data)
        if kind:
            return kind.mime
    header = data[:16]
    if header.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return "image/webp"
    if header.startswith(b"GIF87a") or header.startswith(b"GIF89a"):
        return "image/gif"
    if header.startswith(b"%PDF-"):
        return "application/pdf"
    if header.startswith(b"PK\x03\x04") or header.startswith(b"PK\x05\x06") or header.startswith(b"PK\x07\x08"):
        return "application/zip"
    return None


def _decoded_text(data: bytes) -> str | None:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _looks_like_svg(text: str) -> bool:
    sample = text[:1000].lstrip("\ufeff \t\r\n").lower()
    return "<svg" in sample or sample.startswith("<?xml") and "<svg" in sample


def _looks_like_html(text: str) -> bool:
    sample = text[:1000].lstrip("\ufeff \t\r\n").lower()
    return sample.startswith("<!doctype html") or sample.startswith("<html") or "<script" in sample


def _declared_allowed(declared_type: str) -> bool:
    if declared_type.startswith(("image/", "video/", "audio/")):
        return True
    return declared_type in {"application/pdf", "application/json", "application/zip", "text/plain"}


def _kind(content_type: str) -> str:
    if content_type.startswith("image/"):
        return AssetKind.IMAGE
    if content_type.startswith(("video/", "audio/")):
        return AssetKind.VIDEO
    return AssetKind.FILE


def _validate_image_dimensions(image: Image.Image) -> None:
    width, height = image.size
    if width <= 0 or height <= 0 or width > MAX_IMAGE_DIMENSION or height > MAX_IMAGE_DIMENSION:
        raise UploadRejected(f"Image dimensions must be between 1 and {MAX_IMAGE_DIMENSION}px per side")


def _reencode_image(data: bytes, content_type: str) -> bytes:
    fmt_by_mime = {
        "image/jpeg": "JPEG",
        "image/png": "PNG",
        "image/webp": "WEBP",
    }
    try:
        with Image.open(BytesIO(data)) as image:
            _validate_image_dimensions(image)
            clean = ImageOps.exif_transpose(image)
            out = BytesIO()
            fmt = fmt_by_mime[content_type]
            if fmt == "JPEG" and clean.mode not in ("RGB", "L"):
                clean = clean.convert("RGB")
            save_kwargs = {"format": fmt}
            if fmt == "JPEG":
                save_kwargs.update({"quality": 92, "optimize": True})
            elif fmt == "WEBP":
                save_kwargs.update({"quality": 92, "method": 4})
            clean.save(out, **save_kwargs)
            return out.getvalue()
    except Image.DecompressionBombError as exc:
        raise UploadRejected("Image is too large to process safely") from exc
    except (OSError, UnidentifiedImageError, KeyError) as exc:
        raise UploadRejected("Invalid image file") from exc


def _validate_gif(data: bytes) -> bytes:
    try:
        with Image.open(BytesIO(data)) as image:
            if image.format != "GIF":
                raise UploadRejected("Invalid GIF file")
            _validate_image_dimensions(image)
            image.verify()
    except Image.DecompressionBombError as exc:
        raise UploadRejected("Image is too large to process safely") from exc
    except (OSError, UnidentifiedImageError) as exc:
        raise UploadRejected("Invalid GIF file") from exc
    return data


def _validate_zip(data: bytes) -> bytes:
    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_ZIP_ENTRIES:
                raise UploadRejected(f"ZIP contains more than {MAX_ZIP_ENTRIES} entries")
            total_uncompressed = 0
            for info in infos:
                if info.flag_bits & 0x1:
                    raise UploadRejected("Encrypted ZIP entries are not accepted")
                name = info.filename.replace("\\", "/")
                if name.startswith("/") or ".." in name.split("/"):
                    raise UploadRejected("ZIP entries must stay inside the archive root")
                total_uncompressed += int(info.file_size or 0)
                compressed = max(int(info.compress_size or 0), 1)
                if info.file_size and info.file_size / compressed > MAX_ZIP_COMPRESSION_RATIO:
                    raise UploadRejected("ZIP compression ratio is too high")
            if total_uncompressed > MAX_ZIP_UNCOMPRESSED_BYTES:
                raise UploadRejected("ZIP uncompressed size exceeds 100MB")
    except zipfile.BadZipFile as exc:
        raise UploadRejected("Invalid ZIP file") from exc
    return data


def _validate_text(data: bytes, content_type: str) -> bytes:
    text = _decoded_text(data)
    if text is None:
        raise UploadRejected("Text uploads must be UTF-8")
    if _looks_like_svg(text):
        raise UploadRejected("SVG uploads are not accepted")
    if _looks_like_html(text):
        raise UploadRejected("HTML uploads are not accepted")
    if content_type == "application/json":
        try:
            json.loads(text)
        except json.JSONDecodeError as exc:
            raise UploadRejected("Invalid JSON file") from exc
    return data


def _scan_with_clamav(data: bytes) -> str:
    mode = (settings.UPLOAD_SCAN or "off").lower()
    if mode == "off":
        return "skipped"
    if mode != "clamav":
        raise UploadRejected(f"Unsupported UPLOAD_SCAN mode: {settings.UPLOAD_SCAN}", status_code=500)
    try:
        import clamd

        client = clamd.ClamdNetworkSocket(host=settings.CLAMD_HOST, port=settings.CLAMD_PORT, timeout=10)
        client.ping()
        result = client.instream(BytesIO(data))
    except Exception as exc:  # noqa: BLE001
        raise UploadScannerUnavailable("Upload scanner is unavailable") from exc
    verdict = next(iter(result.values())) if result else ("ERROR", "empty scan result")
    status, reason = verdict[0], verdict[1] if len(verdict) > 1 else ""
    if status == "OK":
        return "clean"
    if status == "FOUND":
        raise UploadRejected(f"Upload blocked by malware scanner: {reason or 'malware'}")
    raise UploadScannerUnavailable("Upload scanner returned an error")


def sanitize_upload(filename: str, data: bytes, declared_type: str | None) -> SafeUpload:
    declared_type = (declared_type or "application/octet-stream").split(";")[0].strip().lower()
    if declared_type == "image/svg+xml":
        raise UploadRejected("SVG uploads are not accepted")
    if declared_type != "application/octet-stream" and not _declared_allowed(declared_type):
        raise UploadRejected(f"Unsupported file type: {declared_type}")

    sniffed_type = _guess_mime(data)
    text = _decoded_text(data) if sniffed_type is None else None
    if text is not None and _looks_like_svg(text):
        raise UploadRejected("SVG uploads are not accepted")
    if text is not None and _looks_like_html(text):
        raise UploadRejected("HTML uploads are not accepted")

    content_type = sniffed_type
    content = data
    if content_type in {"image/jpeg", "image/png", "image/webp"}:
        content = _reencode_image(data, content_type)
    elif content_type == "image/gif":
        content = _validate_gif(data)
    elif content_type == "application/zip":
        content = _validate_zip(data)
    elif content_type in {"application/pdf"} or (content_type or "").startswith(("video/", "audio/")):
        content = data
    elif declared_type in {"text/plain", "application/json"} and text is not None:
        content_type = declared_type
        content = _validate_text(data, content_type)
    else:
        raise UploadRejected(f"Unsupported file type: {declared_type}")

    scan_status = _scan_with_clamav(content)
    return SafeUpload(
        filename=filename,
        content=content,
        content_type=content_type,
        kind=_kind(content_type),
        scan_status=scan_status,
    )


def presigned_asset_url(asset: Asset) -> str | None:
    if asset.scan_status not in {"clean", "skipped"}:
        return None
    if asset.kind == AssetKind.IMAGE:
        return s3.presigned_url(asset.oss_key)
    return s3.presigned_url(
        asset.oss_key,
        response_content_disposition=f'attachment; filename="{asset.filename}"',
    )
