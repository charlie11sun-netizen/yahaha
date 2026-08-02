"""Retention application service for memory evidence and derived profiles."""

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models import (
    MemoryEntity,
    MemoryEntityLink,
    MemoryItem,
    MemoryProfileVersion,
    MemorySettings,
)
from app.services.memory_profile_evidence import remove_evidence_from_profiles
from app.services.memory_repository import utc_now


def purge_expired_memories(
    db: Session,
    user_id: str,
    *,
    settings_row: MemorySettings | None = None,
    now: datetime | None = None,
) -> int:
    settings_row = settings_row or db.get(MemorySettings, user_id)
    if not settings_row or not settings_row.retention_days:
        return 0
    cutoff = (now or utc_now()) - timedelta(days=int(settings_row.retention_days))
    expired = (
        db.query(MemoryItem)
        .filter(MemoryItem.user_id == user_id, MemoryItem.created_at < cutoff)
        .all()
    )
    if not expired:
        return 0

    expired_ids = [item.id for item in expired]
    remove_evidence_from_profiles(
        db,
        expired_ids,
        reason="Evidence expired under the user's retention policy.",
        hard_delete_empty=True,
    )
    db.query(MemoryProfileVersion).filter(
        MemoryProfileVersion.source_memory_id.in_(expired_ids)
    ).delete(synchronize_session=False)
    db.query(MemoryEntityLink).filter(
        MemoryEntityLink.memory_id.in_(expired_ids)
    ).delete(synchronize_session=False)
    db.query(MemoryItem).filter(MemoryItem.id.in_(expired_ids)).delete(
        synchronize_session=False
    )

    linked_entity_ids = db.query(MemoryEntityLink.entity_id)
    db.query(MemoryEntity).filter(
        MemoryEntity.user_id == user_id,
        ~MemoryEntity.id.in_(linked_entity_ids),
    ).delete(synchronize_session=False)
    db.flush()
    return len(expired_ids)


__all__ = ["purge_expired_memories"]
