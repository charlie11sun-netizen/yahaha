from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, rate_limit
from app.db.session import get_db
from app.schemas import MemoryCreateIn, MemorySettingsIn, MemoryUpdateIn
from app.services import memory as memory_service

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
    db.commit()
    db.refresh(item)
    return memory_service.memory_out(item)


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
    memory_service.update_memory(item, **body.model_dump(exclude_unset=True))
    db.commit()
    db.refresh(item)
    return memory_service.memory_out(item)


@router.delete("/{memory_id}")
def delete_memory(memory_id: str, user=Depends(get_current_user), db: Session = Depends(get_db)):
    item = memory_service.get_owned_memory(db, user.id, memory_id)
    if not item:
        raise HTTPException(status_code=404, detail="Memory not found")
    memory_service.soft_delete_memory(item)
    db.commit()
    return {"ok": True}
