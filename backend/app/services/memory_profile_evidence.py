"""Memory profile evidence removal and restoration."""

from __future__ import annotations

from typing import Iterable

from sqlalchemy.orm import Session

from app.models import MemoryItem, MemoryProfile, MemoryProfileEvidence, MemoryProfileVersion
from app.models.common import now_utc
from app.models.memory import (
    MemoryExplicitness,
    MemoryProfileOperation,
    MemoryProfileStatus,
    MemoryScope,
    MemoryStatus,
)
from app.services.memory_profile_common import (
    USER_PROMOTION_DISTINCT_GAMES,
    candidate_expires_at,
    count_distinct_supporting_games,
    profile_number,
    record_profile_version,
    refresh_profile_embedding,
)


def _evidence_rows(db: Session, profile_id: str, *, active: bool):
    return (
        db.query(MemoryProfileEvidence, MemoryItem)
        .join(MemoryItem, MemoryItem.id == MemoryProfileEvidence.memory_id)
        .filter(
            MemoryProfileEvidence.profile_id == profile_id,
            MemoryProfileEvidence.is_active.is_(active),
            MemoryItem.status != MemoryStatus.DELETED,
        )
        .order_by(MemoryItem.created_at.desc(), MemoryProfileEvidence.created_at.desc())
        .all()
    )


def _active_evidence_rows(db: Session, profile_id: str):
    return _evidence_rows(db, profile_id, active=True)


def _apply_evidence_state(profile: MemoryProfile, rows) -> None:
    latest, latest_item = rows[0]
    previous_summary = profile.summary_text
    profile.source_memory_id = latest.memory_id
    profile.value_text = latest.value_text
    profile.summary_text = latest.summary_text
    profile.evidence_span = latest.evidence_span
    profile.scope_confidence = max(profile_number(link.scope_confidence) for link, _ in rows)
    profile.explicitness = latest.explicitness
    profile.support_count = len({link.memory_id for link, _ in rows})
    base_confidence = max(profile_number(link.confidence) for link, _ in rows)
    profile.confidence = round(
        min(0.98, base_confidence + 0.07 * max(0, profile.support_count - 1)), 3
    )
    profile.last_supported_at = latest_item.created_at
    profile.updated_at = now_utc()
    refresh_profile_embedding(profile, previous_summary)


def _restore_previous_profile(db: Session, removed_profile: MemoryProfile, *, reason: str) -> None:
    previous = (
        db.query(MemoryProfile)
        .filter(
            MemoryProfile.user_id == removed_profile.user_id,
            MemoryProfile.scope_type == removed_profile.scope_type,
            MemoryProfile.scope_id == removed_profile.scope_id,
            MemoryProfile.profile_key == removed_profile.profile_key,
            MemoryProfile.status == MemoryProfileStatus.SUPERSEDED,
            MemoryProfile.id != removed_profile.id,
        )
        .order_by(MemoryProfile.updated_at.desc())
        .all()
    )
    for profile in previous:
        rows = _active_evidence_rows(db, profile.id)
        if not rows:
            continue
        _apply_evidence_state(profile, rows)
        profile.status = MemoryProfileStatus.ACTIVE
        profile.expires_at = None
        profile.version += 1
        source = db.get(MemoryItem, profile.source_memory_id)
        if source and source.status == MemoryStatus.SUPERSEDED:
            source.status = MemoryStatus.ACTIVE
            source.supersedes_id = None
            source.updated_at = now_utc()
        record_profile_version(
            db,
            profile,
            MemoryProfileOperation.RESTORED,
            reason=reason,
        )
        return


def remove_evidence_from_profiles(
    db: Session,
    memory_ids: Iterable[str],
    *,
    reason: str,
    hard_delete_empty: bool = False,
) -> None:
    ids = list(dict.fromkeys(memory_id for memory_id in memory_ids if memory_id))
    if not ids:
        return
    profile_ids = {
        row[0]
        for row in db.query(MemoryProfileEvidence.profile_id)
        .filter(MemoryProfileEvidence.memory_id.in_(ids))
        .all()
    }
    profiles = (
        db.query(MemoryProfile).filter(MemoryProfile.id.in_(profile_ids)).all()
        if profile_ids
        else []
    )
    db.query(MemoryProfileEvidence).filter(
        MemoryProfileEvidence.memory_id.in_(ids)
    ).delete(synchronize_session=False)
    db.flush()

    for profile in profiles:
        was_active = profile.status == MemoryProfileStatus.ACTIVE
        rows = _active_evidence_rows(db, profile.id)
        if not rows and was_active and _evidence_rows(db, profile.id, active=False):
            db.query(MemoryProfileEvidence).filter(
                MemoryProfileEvidence.profile_id == profile.id,
                MemoryProfileEvidence.is_active.is_(False),
            ).update({MemoryProfileEvidence.is_active: True}, synchronize_session=False)
            db.flush()
            rows = _active_evidence_rows(db, profile.id)
        if rows:
            _apply_evidence_state(profile, rows)
            if (
                profile.status == MemoryProfileStatus.ACTIVE
                and profile.scope_type == MemoryScope.USER
                and profile.explicitness == MemoryExplicitness.INFERRED
                and count_distinct_supporting_games(db, profile) < USER_PROMOTION_DISTINCT_GAMES
            ):
                profile.status = MemoryProfileStatus.CANDIDATE
                profile.expires_at = candidate_expires_at()
            profile.version += 1
            record_profile_version(
                db,
                profile,
                MemoryProfileOperation.EVIDENCE_REMOVED,
                reason=reason,
            )
            continue

        if hard_delete_empty:
            db.query(MemoryProfileVersion).filter(
                MemoryProfileVersion.profile_id == profile.id
            ).delete(synchronize_session=False)
            db.query(MemoryProfileEvidence).filter(
                MemoryProfileEvidence.profile_id == profile.id
            ).delete(synchronize_session=False)
            db.delete(profile)
            db.flush()
        else:
            profile.status = MemoryProfileStatus.DELETED
            profile.expires_at = None
            profile.version += 1
            profile.updated_at = now_utc()
            record_profile_version(
                db,
                profile,
                MemoryProfileOperation.DELETED,
                reason=reason,
            )
        if was_active:
            _restore_previous_profile(db, profile, reason="Previous value restored after evidence removal.")


def retire_profiles_for_memory(db: Session, memory_id: str, *, reason: str) -> None:
    remove_evidence_from_profiles(db, [memory_id], reason=reason)


__all__ = ["remove_evidence_from_profiles", "retire_profiles_for_memory"]
