"""Canonical in-memory representation for generated project and runtime files.

LangGraph checkpoints must remain JSON serializable, so binary files are stored
as base64 while text files keep their readable ``content`` field.  All build,
validation, sandbox, and publishing code goes through this module instead of
assuming every artifact is UTF-8 source code.
"""
from __future__ import annotations

import base64
import hashlib
import mimetypes
import posixpath
from pathlib import PurePosixPath


TEXT_EXTENSIONS = {
    ".css",
    ".csv",
    ".html",
    ".js",
    ".json",
    ".jsx",
    ".map",
    ".md",
    ".mjs",
    ".svg",
    ".ts",
    ".tsx",
    ".txt",
    ".xml",
}

_CONTENT_TYPES = {
    ".css": "text/css; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".mjs": "application/javascript; charset=utf-8",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".ts": "text/plain; charset=utf-8",
    ".tsx": "text/plain; charset=utf-8",
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".ogg": "audio/ogg",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".wasm": "application/wasm",
}


class ArtifactError(ValueError):
    """Raised when an artifact is malformed or escapes its logical root."""


def normalize_artifact_path(path: str) -> str:
    value = str(path or "").replace("\\", "/").lstrip("/")
    normalized = posixpath.normpath(value)
    if normalized in {"", "."}:
        raise ArtifactError("artifact path is empty")
    parts = PurePosixPath(normalized).parts
    if any(part in {"", ".", ".."} for part in parts):
        raise ArtifactError(f"invalid artifact path: {path!r}")
    if any(part.startswith(".") for part in parts):
        raise ArtifactError(f"hidden artifact path is not allowed: {path!r}")
    return "/".join(parts)


def artifact_bytes(file: dict) -> bytes:
    if file.get("content_b64") is not None:
        try:
            return base64.b64decode(str(file.get("content_b64") or ""), validate=True)
        except Exception as exc:  # noqa: BLE001
            raise ArtifactError(f"invalid base64 content for {file.get('path')!r}") from exc
    content = file.get("content")
    if isinstance(content, bytes):
        return content
    return str(content or "").encode("utf-8")


def artifact_text(file: dict) -> str | None:
    if file.get("content_b64") is None:
        return str(file.get("content") or "")
    path = normalize_artifact_path(str(file.get("path") or ""))
    if PurePosixPath(path).suffix.lower() not in TEXT_EXTENSIONS:
        return None
    try:
        return artifact_bytes(file).decode("utf-8")
    except UnicodeDecodeError:
        return None


def content_type_for(path: str, declared: str | None = None) -> str:
    if declared:
        return str(declared)
    suffix = PurePosixPath(path).suffix.lower()
    if suffix in _CONTENT_TYPES:
        return _CONTENT_TYPES[suffix]
    guessed, _ = mimetypes.guess_type(path)
    return guessed or "application/octet-stream"


def artifact_content_type(file: dict) -> str:
    path = normalize_artifact_path(str(file.get("path") or ""))
    return content_type_for(path, file.get("content_type"))


def artifact_size(file: dict) -> int:
    return len(artifact_bytes(file))


def artifact_sha256(file: dict) -> str:
    return hashlib.sha256(artifact_bytes(file)).hexdigest()


def text_artifact(path: str, content: str, content_type: str | None = None) -> dict:
    normalized = normalize_artifact_path(path)
    return {
        "path": normalized,
        "content": str(content),
        "content_type": content_type_for(normalized, content_type),
    }


def binary_artifact(path: str, content: bytes, content_type: str | None = None) -> dict:
    normalized = normalize_artifact_path(path)
    return {
        "path": normalized,
        "content_b64": base64.b64encode(content).decode("ascii"),
        "content_type": content_type_for(normalized, content_type),
    }


def artifact_from_bytes(path: str, content: bytes, content_type: str | None = None) -> dict:
    normalized = normalize_artifact_path(path)
    if PurePosixPath(normalized).suffix.lower() in TEXT_EXTENSIONS:
        try:
            return text_artifact(normalized, content.decode("utf-8"), content_type)
        except UnicodeDecodeError:
            pass
    return binary_artifact(normalized, content, content_type)


def runtime_artifact(file: dict) -> dict:
    """Map ``public/foo`` from a Vite project to runtime path ``foo``."""
    path = normalize_artifact_path(str(file.get("path") or ""))
    if path.startswith("public/"):
        path = path[len("public/") :]
    out = dict(file)
    out["path"] = path
    return out
