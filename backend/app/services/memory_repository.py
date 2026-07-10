"""Persistence operations for memory items and user memory settings."""

import re
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import MemoryItem, MemorySettings
from app.models.memory import MemorySource, MemoryStatus
from app.services import memory_embeddings


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def clean_memory_text(text: str | None, limit: int = 4000) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()[:limit]


def memory_embedding_text(raw_text: str, extracted_text: str | None) -> str:
    extracted = clean_memory_text(extracted_text)
    raw = clean_memory_text(raw_text)
    return f"{raw}\n{extracted}" if extracted and extracted != raw else raw


def _embed_one(
    raw_text: str,
    extracted_text: str | None,
) -> tuple[list[float] | None, str | None]:
    vectors = memory_embeddings.embed_texts(
        [memory_embedding_text(raw_text, extracted_text)]
    )
    if not vectors:
        return None, None
    return vectors[0], memory_embeddings.embedding_model()


def _safe_confidence(value) -> float:
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except Exception:  # noqa: BLE001
        return 1.0


def memory_out(item: MemoryItem) -> dict:
    return {
        "id": item.id,
        "user_id": item.user_id,
        "scope_type": item.scope_type,
        "scope_id": item.scope_id,
        "category": item.category,
        "raw_text": item.raw_text,
        "extracted_text": item.extracted_text,
        "source_type": item.source_type,
        "source_task_id": item.source_task_id,
        "source_game_id": item.source_game_id,
        "source_version": item.source_version,
        "importance": item.importance,
        "confidence": _safe_confidence(item.confidence),
        "pinned": item.pinned,
        "status": item.status,
        "supersedes_id": item.supersedes_id,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


def settings_out(settings: MemorySettings) -> dict:
    return {
        "enabled": settings.enabled,
        "allow_cross_game_memory": settings.allow_cross_game_memory,
        "allow_memory_extraction": settings.allow_memory_extraction,
        "retention_days": settings.retention_days,
        "created_at": settings.created_at.isoformat() if settings.created_at else None,
        "updated_at": settings.updated_at.isoformat() if settings.updated_at else None,
    }


def get_or_create_settings(db: Session, user_id: str) -> MemorySettings:
    settings = db.get(MemorySettings, user_id)
    if settings:
        return settings
    settings = MemorySettings(user_id=user_id)
    db.add(settings)
    db.flush()
    return settings


def create_memory(
    db: Session,
    user_id: str,
    *,
    scope_type: str,
    scope_id: str | None,
    category: str,
    raw_text: str,
    extracted_text: str | None = None,
    source_type: str = MemorySource.MANUAL,
    source_task_id: str | None = None,
    source_game_id: str | None = None,
    source_version: str | None = None,
    importance: int = 3,
    confidence: float = 1.0,
    pinned: bool = False,
) -> MemoryItem:
    return create_memories_batch(
        db,
        user_id,
        [
            {
                "scope_type": scope_type,
                "scope_id": scope_id,
                "category": category,
                "raw_text": raw_text,
                "extracted_text": extracted_text,
                "source_type": source_type,
                "source_task_id": source_task_id,
                "source_game_id": source_game_id,
                "source_version": source_version,
                "importance": importance,
                "confidence": confidence,
                "pinned": pinned,
            }
        ],
    )[0]


def create_memories_batch(
    db: Session,
    user_id: str,
    candidates: list[dict],
) -> list[MemoryItem]:
    if not candidates:
        return []
    prepared = []
    for candidate in candidates:
        raw_text = clean_memory_text(candidate.get("raw_text"))
        extracted_text = (
            clean_memory_text(candidate.get("extracted_text"))
            if candidate.get("extracted_text")
            else None
        )
        prepared.append((candidate, raw_text, extracted_text))
    vectors = memory_embeddings.embed_texts(
        [
            memory_embedding_text(raw_text, extracted_text)
            for _, raw_text, extracted_text in prepared
        ]
    )
    model = memory_embeddings.embedding_model()
    now = utc_now()
    items = []
    for index, (candidate, raw_text, extracted_text) in enumerate(prepared):
        vector = vectors[index] if vectors and index < len(vectors) else None
        item = MemoryItem(
            user_id=user_id,
            scope_type=candidate["scope_type"],
            scope_id=candidate.get("scope_id"),
            category=candidate["category"],
            raw_text=raw_text,
            extracted_text=extracted_text,
            source_type=candidate.get("source_type", MemorySource.MANUAL),
            source_task_id=candidate.get("source_task_id"),
            source_game_id=candidate.get("source_game_id"),
            source_version=candidate.get("source_version"),
            importance=max(1, min(int(candidate.get("importance", 3)), 5)),
            confidence=max(0.0, min(float(candidate.get("confidence", 1.0)), 1.0)),
            pinned=bool(candidate.get("pinned", False)),
            status=MemoryStatus.ACTIVE,
            embedding=vector,
            embedding_model=model if vector else None,
            embedding_updated_at=now if vector else None,
        )
        db.add(item)
        items.append(item)
    db.flush()
    return items


def update_memory(item: MemoryItem, **patch) -> MemoryItem:
    text_changed = False
    for key in (
        "category",
        "raw_text",
        "extracted_text",
        "importance",
        "pinned",
        "status",
    ):
        if key not in patch or patch[key] is None:
            continue
        value = patch[key]
        if key in {"raw_text", "extracted_text"}:
            value = clean_memory_text(value)
            text_changed = True
        if key == "importance":
            value = max(1, min(int(value), 5))
        setattr(item, key, value)
    if text_changed:
        embedding, embedding_model = _embed_one(item.raw_text, item.extracted_text)
        item.embedding = embedding
        item.embedding_model = embedding_model
        item.embedding_updated_at = utc_now() if embedding else None
    item.updated_at = utc_now()
    return item


def soft_delete_memory(item: MemoryItem) -> MemoryItem:
    item.status = MemoryStatus.DELETED
    item.updated_at = utc_now()
    return item


__all__ = [
    "clean_memory_text",
    "create_memories_batch",
    "create_memory",
    "get_or_create_settings",
    "memory_embedding_text",
    "memory_out",
    "settings_out",
    "soft_delete_memory",
    "update_memory",
    "utc_now",
]
