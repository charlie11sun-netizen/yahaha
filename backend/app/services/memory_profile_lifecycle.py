"""Memory profile conflict, candidate, and reconciliation lifecycle."""

from __future__ import annotations

from app.services.memory_profile_common import *
from app.services.memory_profile_extraction import (
    _refresh_embedding_for_summary,
    _value_for,
    extract_profile_claims,
)

def _same_value(left: str, right: str) -> bool:
    a, b = _normalized(left), _normalized(right)
    return bool(a and b and (a == b or (len(a) >= 8 and a in b) or (len(b) >= 8 and b in a)))


def _active_conflict(db: Session, user_id: str, claim: dict) -> MemoryProfile | None:
    return (
        db.query(MemoryProfile)
        .filter(
            MemoryProfile.user_id == user_id,
            MemoryProfile.scope_type == claim["scope_type"],
            MemoryProfile.scope_id == claim["scope_id"],
            MemoryProfile.profile_key == claim["profile_key"],
            MemoryProfile.status == MemoryProfileStatus.ACTIVE,
        )
        .order_by(MemoryProfile.updated_at.desc())
        .first()
    )


def _matching_candidate(db: Session, user_id: str, claim: dict) -> MemoryProfile | None:
    candidates = (
        db.query(MemoryProfile)
        .filter(
            MemoryProfile.user_id == user_id,
            MemoryProfile.scope_type == claim["scope_type"],
            MemoryProfile.scope_id == claim["scope_id"],
            MemoryProfile.profile_key == claim["profile_key"],
            MemoryProfile.status == MemoryProfileStatus.CANDIDATE,
        )
        .order_by(MemoryProfile.updated_at.desc())
        .limit(20)
        .all()
    )
    return next((profile for profile in candidates if _same_value(profile.value_text, claim["value_text"])), None)


def _retire_memory_source_if_unused(db: Session, memory_id: str | None, replacement: MemoryItem | None) -> None:
    if not memory_id or not replacement:
        return
    active_count = (
        db.query(MemoryProfile.id)
        .filter(
            MemoryProfile.source_memory_id == memory_id,
            MemoryProfile.status == MemoryProfileStatus.ACTIVE,
        )
        .count()
    )
    if active_count:
        return
    old_item = db.get(MemoryItem, memory_id)
    if old_item and old_item.status == MemoryStatus.ACTIVE:
        old_item.status = MemoryStatus.SUPERSEDED
        old_item.supersedes_id = None
        old_item.updated_at = now_utc()
        replacement.supersedes_id = old_item.id


def _retire_source_if_unused(db: Session, profile: MemoryProfile, replacement: MemoryItem | None) -> None:
    _retire_memory_source_if_unused(db, profile.source_memory_id, replacement)


def _support_adjusted_confidence(profile: MemoryProfile, claim_confidence: float) -> float:
    support_count = max(1, int(profile.support_count or 1))
    base = max(_float(profile.confidence), claim_confidence)
    return round(min(0.98, base + 0.07 * max(0, support_count - 1)), 3)


def _reinforce_profile(
    db: Session,
    profile: MemoryProfile,
    item: MemoryItem,
    claim: dict,
    *,
    reason: str,
) -> MemoryProfile:
    if profile.source_memory_id != item.id:
        profile.support_count = max(1, int(profile.support_count or 1)) + 1
    previous_summary = profile.summary_text
    profile.confidence = _support_adjusted_confidence(profile, claim["confidence"])
    profile.scope_confidence = max(_float(profile.scope_confidence), claim["scope_confidence"])
    profile.summary_text = claim["summary_text"]
    profile.evidence_span = claim["evidence_span"]
    profile.source_memory_id = item.id
    profile.last_supported_at = now_utc()
    _refresh_embedding_for_summary(profile, previous_summary)
    if profile.status == MemoryProfileStatus.CANDIDATE:
        profile.expires_at = _candidate_expires_at()
    profile.version += 1
    profile.updated_at = now_utc()
    _link_profile_evidence(db, profile, item, claim)
    _record_version(
        db,
        profile,
        MemoryProfileOperation.REINFORCED,
        source_memory_id=item.id,
        reason=reason,
    )
    return profile


def _supersede_profile(
    db: Session,
    profile: MemoryProfile,
    *,
    source_memory_id: str | None,
    reason: str,
) -> None:
    profile.status = MemoryProfileStatus.SUPERSEDED
    profile.version += 1
    profile.updated_at = now_utc()
    _record_version(
        db,
        profile,
        MemoryProfileOperation.SUPERSEDED,
        source_memory_id=source_memory_id,
        reason=reason,
    )


def _distinct_supporting_games(db: Session, profile: MemoryProfile) -> int:
    db.flush()
    rows = (
        db.query(MemoryItem.source_game_id, MemoryItem.scope_type, MemoryItem.scope_id)
        .join(MemoryProfileEvidence, MemoryProfileEvidence.memory_id == MemoryItem.id)
        .filter(
            MemoryProfileEvidence.profile_id == profile.id,
            MemoryProfileEvidence.is_active.is_(True),
            MemoryItem.status != MemoryStatus.DELETED,
        )
        .distinct()
        .all()
    )
    games = {
        source_game_id or (scope_id if scope_type == MemoryScope.GAME else None)
        for source_game_id, scope_type, scope_id in rows
    }
    games.discard(None)
    return len(games)


def _promote_candidate_if_ready(
    db: Session,
    profile: MemoryProfile,
    item: MemoryItem,
    *,
    force: bool = False,
    reason: str | None = None,
) -> bool:
    if profile.status != MemoryProfileStatus.CANDIDATE:
        return False
    if profile.scope_type == MemoryScope.USER:
        # A global preference is promoted by breadth, not by repetition:
        # the same value must have been expressed in distinct games.
        ready = (
            _float(profile.confidence) >= CANDIDATE_CONFIDENCE_THRESHOLD
            and _float(profile.scope_confidence) >= 0.80
            and _distinct_supporting_games(db, profile) >= USER_PROMOTION_DISTINCT_GAMES
        )
        if ready and not reason:
            reason = "Candidate preference was independently supported in multiple games."
    else:
        ready = (
            int(profile.support_count or 1) >= CANDIDATE_SUPPORT_THRESHOLD
            and _float(profile.confidence) >= CANDIDATE_CONFIDENCE_THRESHOLD
            and _float(profile.scope_confidence) >= 0.80
        )
    if not (ready or force):
        return False

    conflict = db.get(MemoryProfile, profile.conflicts_with_id) if profile.conflicts_with_id else None
    if not conflict:
        conflict = _active_conflict(db, profile.user_id, {
            "scope_type": profile.scope_type,
            "scope_id": profile.scope_id,
            "profile_key": profile.profile_key,
        })
    if conflict and conflict.id != profile.id and conflict.status == MemoryProfileStatus.ACTIVE:
        if _same_value(conflict.value_text, profile.value_text):
            profile.status = MemoryProfileStatus.DELETED
            profile.version += 1
            profile.updated_at = now_utc()
            _record_version(
                db,
                profile,
                MemoryProfileOperation.DELETED,
                source_memory_id=item.id,
                reason="Candidate duplicated an already active value.",
            )
            return False
        _supersede_profile(
            db,
            conflict,
            source_memory_id=item.id,
            reason="A repeatedly supported candidate replaced this active value.",
        )
        _retire_source_if_unused(db, conflict, item)

    profile.status = MemoryProfileStatus.ACTIVE
    profile.expires_at = None
    profile.version += 1
    profile.updated_at = now_utc()
    _record_version(
        db,
        profile,
        MemoryProfileOperation.AUTO_PROMOTED,
        source_memory_id=item.id,
        reason=reason or "Candidate reached repeated independent support and confidence thresholds.",
    )
    return True


def _create_profile(
    db: Session,
    item: MemoryItem,
    claim: dict,
    *,
    status: str,
    conflicts_with_id: str | None = None,
) -> MemoryProfile:
    now = now_utc()
    vector = claim.get("embedding")
    if not vector:
        embedded = memory_embeddings.embed_texts([_clean(claim["summary_text"], 500)])
        vector = embedded[0] if embedded else None
    profile = MemoryProfile(
        user_id=item.user_id,
        scope_type=claim["scope_type"],
        scope_id=claim["scope_id"],
        profile_key=claim["profile_key"],
        category=claim["category"],
        value_text=claim["value_text"],
        summary_text=claim["summary_text"],
        evidence_span=claim["evidence_span"],
        confidence=claim["confidence"],
        scope_confidence=claim["scope_confidence"],
        explicitness=claim["explicitness"],
        status=status,
        source_memory_id=item.id,
        conflicts_with_id=conflicts_with_id,
        support_count=1,
        utility_score=0.5,
        utility_observation_count=0,
        last_supported_at=now,
        expires_at=_candidate_expires_at() if status == MemoryProfileStatus.CANDIDATE else None,
        embedding=vector,
        embedding_model=memory_embeddings.embedding_model() if vector else None,
        embedding_updated_at=now if vector else None,
        version=1,
    )
    db.add(profile)
    db.flush()
    _link_profile_evidence(db, profile, item, claim)
    return profile


def expire_stale_candidates(db: Session, user_id: str | None = None) -> int:
    q = db.query(MemoryProfile).filter(
        MemoryProfile.status == MemoryProfileStatus.CANDIDATE,
        MemoryProfile.expires_at.isnot(None),
        MemoryProfile.expires_at <= now_utc(),
    )
    if user_id:
        q = q.filter(MemoryProfile.user_id == user_id)
    expired = q.all()
    for profile in expired:
        profile.status = MemoryProfileStatus.DELETED
        profile.version += 1
        profile.updated_at = now_utc()
        _record_version(
            db,
            profile,
            MemoryProfileOperation.EXPIRED,
            reason="Candidate memory expired without enough repeated support.",
        )
    return len(expired)


def _reconcile_claims_for_item(
    db: Session,
    item: MemoryItem,
    claims: list[dict],
) -> list[MemoryProfile]:
    results: list[MemoryProfile] = []
    for claim in claims:
        existing = _active_conflict(db, item.user_id, claim)
        if existing and _same_value(existing.value_text, claim["value_text"]):
            _reinforce_profile(
                db,
                existing,
                item,
                claim,
                reason="New evidence supports the existing active value.",
            )
            results.append(existing)
            continue

        decisive = (
            claim["confidence"] >= 0.80
            and claim["scope_confidence"] >= 0.80
            and claim["explicitness"] != MemoryExplicitness.INFERRED
        )
        candidate = _matching_candidate(db, item.user_id, claim)

        if candidate:
            if existing and not candidate.conflicts_with_id:
                candidate.conflicts_with_id = existing.id
            _reinforce_profile(
                db,
                candidate,
                item,
                claim,
                reason=(
                    "Explicit evidence confirmed the candidate value."
                    if decisive
                    else "Repeated evidence supports the candidate value."
                ),
            )
            _promote_candidate_if_ready(
                db,
                candidate,
                item,
                force=decisive,
                reason=(
                    "Explicit evidence confirmed the candidate memory."
                    if decisive
                    else None
                ),
            )
            results.append(candidate)
            continue

        if not decisive:
            profile = _create_profile(
                db,
                item,
                claim,
                status=MemoryProfileStatus.CANDIDATE,
                conflicts_with_id=existing.id if existing else None,
            )
            _record_version(
                db,
                profile,
                MemoryProfileOperation.CANDIDATE,
                reason="Inferred or ambiguous evidence is stored as an inactive candidate.",
            )
            results.append(profile)
            continue

        if existing:
            _supersede_profile(
                db,
                existing,
                source_memory_id=item.id,
                reason="A newer explicit claim replaced this value in the same scope.",
            )
        profile = _create_profile(
            db,
            item,
            claim,
            status=MemoryProfileStatus.ACTIVE,
            conflicts_with_id=existing.id if existing else None,
        )
        _record_version(
            db,
            profile,
            MemoryProfileOperation.CREATED,
            reason="Explicit evidence created the active profile.",
        )
        if existing:
            _retire_source_if_unused(db, existing, item)
        results.append(profile)
    return results


def reconcile_memory_items(
    db: Session,
    items: list[MemoryItem],
    *,
    claims_by_memory_id: dict[str, list[dict]] | None = None,
    game_id: str | None = None,
    task_id: str | None = None,
) -> list[MemoryProfile]:
    if not items:
        return []
    user_id = items[0].user_id
    if any(item.user_id != user_id for item in items):
        raise ValueError("A memory reconciliation batch must belong to one user")
    # One row lock serializes the whole batch so concurrent tasks cannot create
    # multiple active values for the same user/scope/profile_key.
    db.query(User.id).filter(User.id == user_id).with_for_update().one()
    expire_stale_candidates(db, user_id)
    claims_by_memory_id = claims_by_memory_id or {
        item.id: extract_profile_claims(db, item, game_id=game_id, task_id=task_id)
        for item in items
    }
    results: list[MemoryProfile] = []
    for item in items:
        results.extend(_reconcile_claims_for_item(db, item, claims_by_memory_id.get(item.id, [])))
    return results


def reconcile_memory_item(
    db: Session,
    item: MemoryItem,
    *,
    game_id: str | None = None,
    task_id: str | None = None,
) -> list[MemoryProfile]:
    return reconcile_memory_items(
        db,
        [item],
        game_id=game_id,
        task_id=task_id,
    )


def backfill_missing_profiles(db: Session, user_id: str, *, limit: int = 200) -> int:
    profiled_ids = {
        row[0]
        for row in db.query(MemoryProfileEvidence.memory_id)
        .join(MemoryProfile, MemoryProfile.id == MemoryProfileEvidence.profile_id)
        .filter(MemoryProfile.user_id == user_id)
        .all()
        if row[0]
    }
    q = db.query(MemoryItem).filter(
        MemoryItem.user_id == user_id,
        MemoryItem.status == MemoryStatus.ACTIVE,
    )
    if profiled_ids:
        q = q.filter(~MemoryItem.id.in_(profiled_ids))
    items = q.order_by(MemoryItem.created_at.asc()).limit(max(1, min(limit, 500))).all()
    for item in items:
        reconcile_memory_item(
            db,
            item,
            game_id=item.source_game_id or (item.scope_id if item.scope_type == MemoryScope.GAME else None),
            task_id=item.source_task_id or (item.scope_id if item.scope_type == MemoryScope.TASK else None),
        )
    return len(items)


def correct_profile(
    db: Session,
    profile: MemoryProfile,
    *,
    value_text: str | None = None,
    summary_text: str | None = None,
) -> MemoryProfile:
    from app.services.memory import create_memory

    correction_text = _clean(summary_text or value_text or profile.summary_text, 1000)
    old_source_id = profile.source_memory_id
    source = create_memory(
        db,
        profile.user_id,
        scope_type=profile.scope_type,
        scope_id=profile.scope_id,
        category=profile.category,
        raw_text=correction_text,
        extracted_text=correction_text,
        source_type=MemorySource.MANUAL,
        importance=5,
        confidence=1.0,
        pinned=profile.scope_type == MemoryScope.USER,
    )
    active_conflict = _active_conflict(
        db,
        profile.user_id,
        {
            "scope_type": profile.scope_type,
            "scope_id": profile.scope_id,
            "profile_key": profile.profile_key,
        },
    )
    if active_conflict and active_conflict.id != profile.id:
        _supersede_profile(
            db,
            active_conflict,
            source_memory_id=source.id,
            reason="A manual correction replaced the active value in the same scope.",
        )
    if value_text is not None:
        profile.value_text = _clean(value_text, 500)
    if summary_text is not None:
        profile.summary_text = _clean(summary_text, 1000)
        profile.evidence_span = profile.summary_text
        if value_text is None:
            profile.value_text = _value_for(profile.profile_key, profile.summary_text)
    profile.source_memory_id = source.id
    profile.confidence = 1.0
    profile.scope_confidence = 1.0
    profile.explicitness = MemoryExplicitness.MANUAL
    profile.status = MemoryProfileStatus.ACTIVE
    profile.support_count = 1
    profile.last_supported_at = now_utc()
    profile.expires_at = None
    # Never retain a vector for text that no longer matches it.
    refreshed = memory_embeddings.embed_texts([_clean(profile.summary_text, 500)])
    profile.embedding = refreshed[0] if refreshed else None
    profile.embedding_model = memory_embeddings.embedding_model() if refreshed else None
    profile.embedding_updated_at = now_utc() if refreshed else None
    profile.version += 1
    profile.updated_at = now_utc()
    db.query(MemoryProfileEvidence).filter(
        MemoryProfileEvidence.profile_id == profile.id
    ).update({MemoryProfileEvidence.is_active: False}, synchronize_session=False)
    _link_profile_evidence(
        db,
        profile,
        source,
        {
            "evidence_span": correction_text,
            "value_text": profile.value_text,
            "summary_text": profile.summary_text,
            "confidence": 1.0,
            "scope_confidence": 1.0,
            "explicitness": MemoryExplicitness.MANUAL,
        },
    )
    _record_version(
        db,
        profile,
        MemoryProfileOperation.CORRECTED,
        reason="User manually corrected the profile.",
    )
    _retire_memory_source_if_unused(db, old_source_id, source)
    if active_conflict and active_conflict.id != profile.id:
        _retire_source_if_unused(db, active_conflict, source)
    from app.services import memory_entities

    memory_entities.upsert_claim_entities(
        db,
        user_id=profile.user_id,
        items=[source],
        claims_by_memory_id={
            source.id: [
                {
                    "profile_key": profile.profile_key,
                    "category": profile.category,
                    "entities": [],
                }
            ]
        },
    )
    return profile


def record_profile_utility(
    db: Session,
    *,
    user_id: str | None,
    profile_ids: Iterable[str],
    outcome_score: float,
    reason: str,
) -> list[MemoryProfile]:
    if not user_id:
        return []
    ids = list(dict.fromkeys(profile_id for profile_id in profile_ids if profile_id))
    if not ids:
        return []
    score = _clamp(outcome_score)
    profiles = (
        db.query(MemoryProfile)
        .filter(
            MemoryProfile.user_id == user_id,
            MemoryProfile.id.in_(ids),
            MemoryProfile.status == MemoryProfileStatus.ACTIVE,
        )
        .all()
    )
    for profile in profiles:
        count = int(profile.utility_observation_count or 0)
        old_score = _float(profile.utility_score) if profile.utility_score is not None else 0.5
        profile.utility_score = round(old_score * (1 - UTILITY_ALPHA) + score * UTILITY_ALPHA, 3)
        profile.utility_observation_count = count + 1
        profile.version += 1
        profile.updated_at = now_utc()
        _record_version(
            db,
            profile,
            MemoryProfileOperation.UTILITY_UPDATED,
            reason=reason,
        )
    return profiles


def record_generation_profile_utility(
    db: Session,
    *,
    user_id: str | None,
    state: dict,
) -> list[MemoryProfile]:
    profiles = state.get("retrieved_memory_profiles") or []
    profile_ids = [item.get("id") for item in profiles if isinstance(item, dict)]
    memory_ids = [
        item.get("id")
        for item in (state.get("retrieved_memories") or [])
        if isinstance(item, dict) and item.get("id")
    ]
    if not profile_ids or not memory_ids:
        return []
    attributed_profile_ids = {
        row[0]
        for row in db.query(MemoryProfileEvidence.profile_id)
        .filter(
            MemoryProfileEvidence.profile_id.in_(profile_ids),
            MemoryProfileEvidence.memory_id.in_(memory_ids),
            MemoryProfileEvidence.is_active.is_(True),
        )
        .all()
    }
    if not attributed_profile_ids:
        return []

    valid = bool((state.get("validation_result") or {}).get("valid"))
    gameplay_passed = bool((state.get("gameplay_qa_result") or {}).get("passed"))
    base_score = 1.0 if valid and gameplay_passed else 0.0
    penalty = (
        0.08 * int(state.get("repair_attempts") or 0)
        + 0.10 * int(state.get("gameplay_repair_attempts") or 0)
        + 0.15 * int(state.get("replan_attempts") or 0)
    )
    score = _clamp(base_score - penalty)
    reason = (
        f"Generation outcome utility: validation={valid}, gameplay={gameplay_passed}, "
        f"repair_attempts={state.get('repair_attempts') or 0}, "
        f"gameplay_repair_attempts={state.get('gameplay_repair_attempts') or 0}, "
        f"replan_attempts={state.get('replan_attempts') or 0}."
    )
    return record_profile_utility(
        db,
        user_id=user_id,
        profile_ids=attributed_profile_ids,
        outcome_score=score,
        reason=reason,
    )


__all__ = [name for name in globals() if not name.startswith("__")]
