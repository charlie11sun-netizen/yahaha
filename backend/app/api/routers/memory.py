from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, rate_limit
from app.db.session import get_db
from app.schemas import (
    MemoryCreateIn,
    MemoryProfileUpdateIn,
    MemorySettingsIn,
    MemoryUpdateIn,
)
from app.services import memory as memory_service
from app.services import content_safety
from app.services import memory_entities as entity_service
from app.services import memory_profiles as profile_service

router = APIRouter(prefix="/memory", tags=["memory"])


@router.get("/settings")
def get_memory_settings(user=Depends(get_current_user), db: Session = Depends(get_db)):
    settings = memory_service.get_or_create_settings(db, user.id)
    db.commit()
    return memory_service.settings_out(settings)


@router.patch("/settings")
def update_memory_settings(
    body: MemorySettingsIn,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    settings = memory_service.get_or_create_settings(db, user.id)
    patch = body.model_dump(exclude_unset=True)
    for key, value in patch.items():
        setattr(settings, key, value)
    memory_service.purge_expired_memories(db, user.id, settings_row=settings)
    db.commit()
    db.refresh(settings)
    return memory_service.settings_out(settings)


@router.get("")
def list_memories(
    scope_type: str | None = None,
    scope_id: str | None = None,
    category: str | None = None,
    status: str | None = Query(default="active"),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    items = memory_service.list_memories(
        db,
        user.id,
        scope_type=scope_type,
        scope_id=scope_id,
        category=category,
        status=status,
        limit=limit,
        offset=offset,
    )
    return {"items": [memory_service.memory_out(item) for item in items]}


@router.post("", dependencies=[Depends(rate_limit(60, 3600, "memory_create"))])
def create_memory(body: MemoryCreateIn, user=Depends(get_current_user), db: Session = Depends(get_db)):
    if body.scope_type == "user" and body.scope_id:
        raise HTTPException(status_code=400, detail="User-scope memory must not include scope_id")
    if body.scope_type != "user" and not body.scope_id:
        raise HTTPException(status_code=400, detail="Non-user memory requires scope_id")
    content_safety.ensure_allowed(
        db,
        text=body.raw_text,
        surface="memory.raw_text",
        user_id=user.id,
        object_id=body.scope_id,
    )
    if body.extracted_text:
        content_safety.ensure_allowed(
            db,
            text=body.extracted_text,
            surface="memory.extracted_text",
            user_id=user.id,
            object_id=body.scope_id,
        )
    item = memory_service.create_memory(
        db,
        user.id,
        scope_type=body.scope_type,
        scope_id=body.scope_id,
        category=body.category,
        raw_text=body.raw_text,
        extracted_text=body.extracted_text,
        importance=body.importance,
        pinned=body.pinned,
    )
    claims = profile_service.extract_profile_claims(db, item)
    profile_service.reconcile_memory_items(db, [item], claims_by_memory_id={item.id: claims})
    entity_service.upsert_claim_entities(
        db, user_id=user.id, items=[item], claims_by_memory_id={item.id: claims}
    )
    db.commit()
    db.refresh(item)
    return memory_service.memory_out(item)


@router.get("/profiles")
def list_memory_profiles(
    status: str | None = Query(default=None),
    scope_type: str | None = None,
    scope_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=200),
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    profiles = profile_service.list_profiles(
        db,
        user.id,
        status=status,
        scope_type=scope_type,
        scope_id=scope_id,
        limit=limit,
    )
    db.commit()  # also persists one-time profile backfill for pre-upgrade memories
    return {"items": [profile_service.profile_out(profile) for profile in profiles]}


@router.get("/profiles/{profile_id}/history")
def get_memory_profile_history(
    profile_id: str,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    profile = profile_service.get_owned_profile(db, user.id, profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Memory profile not found")
    return {"items": [profile_service.version_out(item) for item in profile_service.profile_history(db, profile.id)]}


@router.patch("/profiles/{profile_id}")
def update_memory_profile(
    profile_id: str,
    body: MemoryProfileUpdateIn,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    profile = profile_service.get_owned_profile(db, user.id, profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Memory profile not found")
    patch = body.model_dump(exclude_unset=True)
    for key in ("value_text", "summary_text"):
        if patch.get(key):
            content_safety.ensure_allowed(
                db,
                text=patch[key],
                surface=f"memory_profile.{key}",
                user_id=user.id,
                object_id=profile.id,
            )
    profile_service.correct_profile(db, profile, **patch)
    db.commit()
    db.refresh(profile)
    return profile_service.profile_out(profile)


@router.patch("/{memory_id}")
def update_memory(
    memory_id: str,
    body: MemoryUpdateIn,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    item = memory_service.get_owned_memory(db, user.id, memory_id)
    if not item:
        raise HTTPException(status_code=404, detail="Memory not found")
    patch = body.model_dump(exclude_unset=True)
    if patch.get("raw_text"):
        content_safety.ensure_allowed(
            db,
            text=patch["raw_text"],
            surface="memory.raw_text",
            user_id=user.id,
            object_id=item.id,
        )
    if patch.get("extracted_text"):
        content_safety.ensure_allowed(
            db,
            text=patch["extracted_text"],
            surface="memory.extracted_text",
            user_id=user.id,
            object_id=item.id,
        )
    profile_fields_changed = bool({"raw_text", "extracted_text", "category", "status"} & patch.keys())
    if profile_fields_changed:
        profile_service.retire_profiles_for_memory(
            db, item.id, reason="Source memory was edited or changed status by the user."
        )
        entity_service.delete_links_for_memory(db, item.id)
    memory_service.update_memory(item, **patch)
    if profile_fields_changed and item.status == "active":
        claims = profile_service.extract_profile_claims(db, item)
        profile_service.reconcile_memory_items(db, [item], claims_by_memory_id={item.id: claims})
        entity_service.upsert_claim_entities(
            db, user_id=user.id, items=[item], claims_by_memory_id={item.id: claims}
        )
    db.commit()
    db.refresh(item)
    return memory_service.memory_out(item)


@router.delete("/{memory_id}")
def delete_memory(memory_id: str, user=Depends(get_current_user), db: Session = Depends(get_db)):
    item = memory_service.get_owned_memory(db, user.id, memory_id)
    if not item:
        raise HTTPException(status_code=404, detail="Memory not found")
    profile_service.retire_profiles_for_memory(db, item.id, reason="Source memory was deleted by the user.")
    entity_service.delete_links_for_memory(db, item.id)
    memory_service.soft_delete_memory(item)
    db.commit()
    return {"ok": True}
