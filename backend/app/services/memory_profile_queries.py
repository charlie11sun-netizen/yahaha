"""Memory profile read models and retrieval helpers."""

from __future__ import annotations

from typing import Iterable

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.models import MemoryProfile, MemoryProfileVersion, MemorySettings
from app.models.memory import MemoryProfileStatus, MemoryScope
from app.services.memory_profile_common import (
    PROFILE_CONTEXT_CHARS,
    PROFILE_CONTEXT_LIMIT,
    clean_profile_text,
    profile_out,
    scope_priority_expr,
)
from app.services.memory_profile_lifecycle import backfill_missing_profiles, expire_stale_candidates
from app.services.memory_retention import purge_expired_memories


def list_profiles(
    db: Session,
    user_id: str,
    *,
    status: str | None = None,
    scope_type: str | None = None,
    scope_id: str | None = None,
    limit: int = 100,
) -> list[MemoryProfile]:
    purge_expired_memories(db, user_id)
    backfill_missing_profiles(db, user_id)
    expire_stale_candidates(db, user_id)
    q = db.query(MemoryProfile).filter(MemoryProfile.user_id == user_id)
    if status:
        q = q.filter(MemoryProfile.status == status)
    if scope_type:
        q = q.filter(MemoryProfile.scope_type == scope_type)
    if scope_id:
        q = q.filter(MemoryProfile.scope_id == scope_id)
    return q.order_by(MemoryProfile.updated_at.desc()).limit(max(1, min(limit, 200))).all()


def get_owned_profile(db: Session, user_id: str, profile_id: str) -> MemoryProfile | None:
    return (
        db.query(MemoryProfile)
        .filter(MemoryProfile.id == profile_id, MemoryProfile.user_id == user_id)
        .first()
    )


def profile_history(db: Session, profile_id: str) -> list[MemoryProfileVersion]:
    return (
        db.query(MemoryProfileVersion)
        .filter(MemoryProfileVersion.profile_id == profile_id)
        .order_by(MemoryProfileVersion.version.desc(), MemoryProfileVersion.created_at.desc())
        .all()
    )


def retrieve_profiles(
    db: Session,
    *,
    user_id: str,
    game_id: str | None = None,
    task_id: str | None = None,
    categories: Iterable[str] | None = None,
    limit: int = PROFILE_CONTEXT_LIMIT,
) -> list[dict]:
    settings_row = db.get(MemorySettings, user_id)
    if settings_row and not settings_row.enabled:
        return []
    purge_expired_memories(db, user_id, settings_row=settings_row)
    backfill_missing_profiles(db, user_id)
    expire_stale_candidates(db, user_id)
    clauses = []
    if task_id:
        clauses.append(and_(MemoryProfile.scope_type == MemoryScope.TASK, MemoryProfile.scope_id == task_id))
    if game_id:
        clauses.append(and_(MemoryProfile.scope_type == MemoryScope.GAME, MemoryProfile.scope_id == game_id))
    if not settings_row or settings_row.allow_cross_game_memory:
        clauses.append(MemoryProfile.scope_type == MemoryScope.USER)
    if not clauses:
        return []
    q = db.query(MemoryProfile).filter(
        MemoryProfile.user_id == user_id,
        MemoryProfile.status == MemoryProfileStatus.ACTIVE,
        or_(*clauses),
    )
    cats = [category for category in (categories or []) if category]
    if cats:
        q = q.filter(MemoryProfile.category.in_(cats))
    profiles = q.order_by(
        scope_priority_expr(game_id=game_id, task_id=task_id),
        MemoryProfile.confidence.desc(),
        MemoryProfile.support_count.desc(),
        MemoryProfile.updated_at.desc(),
    ).limit(max(1, min(limit, 20))).all()
    return [profile_out(profile) for profile in profiles]


def render_profile_context(items: list[dict], *, max_chars: int = PROFILE_CONTEXT_CHARS) -> str:
    if not items:
        return ""
    lines = ["Active memory profile (current user request wins on conflict):"]
    total = len(lines[0])
    for item in items:
        line = (
            f"- [{item['scope_type']}/{item['category']}/{item['profile_key']}] "
            f"{clean_profile_text(item['summary_text'], 260)} "
            f"(support={item.get('support_count', 1)}, utility={float(item.get('utility_score') or 0.5):.2f})"
        )
        if total + len(line) > max_chars:
            lines.append("- ...")
            break
        lines.append(line)
        total += len(line)
    return "\n".join(lines)


__all__ = [
    "get_owned_profile",
    "list_profiles",
    "profile_history",
    "render_profile_context",
    "retrieve_profiles",
]
