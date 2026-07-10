"""Compatibility facade for memory profile services.

Implementation is split by responsibility across adjacent modules; this module
keeps the historical import path stable for routers, services, and tests.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import MemoryItem, MemoryProfile
from app.services import memory_entities
from app.services.memory_profile_common import profile_out, version_out
from app.services.memory_profile_evidence import (
    remove_evidence_from_profiles,
    retire_profiles_for_memory,
)
from app.services.memory_profile_extraction import (
    extract_profile_claims,
    extract_profile_claims_batch,
    profiles_for_extraction_context,
)
from app.services.memory_profile_lifecycle import (
    apply_profile_correction,
    backfill_missing_profiles,
    expire_stale_candidates,
    reconcile_memory_item,
    reconcile_memory_items,
    record_generation_profile_utility,
    record_profile_utility,
)
from app.services.memory_profile_queries import (
    get_owned_profile,
    list_profiles,
    profile_history,
    render_profile_context,
    retrieve_profiles,
)


def correct_profile(
    db: Session,
    profile: MemoryProfile,
    *,
    value_text: str | None = None,
    summary_text: str | None = None,
) -> MemoryProfile:
    """Apply a profile correction and update its derived entity index."""
    updated = apply_profile_correction(
        db,
        profile,
        value_text=value_text,
        summary_text=summary_text,
    )
    source = db.get(MemoryItem, updated.source_memory_id)
    if source:
        memory_entities.upsert_claim_entities(
            db,
            user_id=updated.user_id,
            items=[source],
            claims_by_memory_id={
                source.id: [
                    {
                        "profile_key": updated.profile_key,
                        "category": updated.category,
                        "entities": [],
                    }
                ]
            },
        )
    return updated


__all__ = [
    "backfill_missing_profiles",
    "correct_profile",
    "expire_stale_candidates",
    "extract_profile_claims",
    "extract_profile_claims_batch",
    "get_owned_profile",
    "list_profiles",
    "profile_history",
    "profile_out",
    "profiles_for_extraction_context",
    "reconcile_memory_item",
    "reconcile_memory_items",
    "record_generation_profile_utility",
    "record_profile_utility",
    "remove_evidence_from_profiles",
    "render_profile_context",
    "retire_profiles_for_memory",
    "retrieve_profiles",
    "version_out",
]
