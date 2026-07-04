import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, rate_limit
from app.core.config import settings
from app.core.errors import TaskErrorCode
from app.core.telemetry import current_request_id
from app.db.session import get_db
from app.models import Asset, Game, GameVersion, GenerationTask
from app.models.common import GameStatus, TaskStatus, now_utc
from app.schemas import TaskCreateIn, TaskRevisionIn
from app.services.serialize import task_out
from app.tasks.generate import generate_game

router = APIRouter(prefix="/tasks", tags=["tasks"])


def _enqueue_generation(task_id: str) -> None:
    headers = {"request_id": current_request_id() or ""}
    if hasattr(generate_game, "apply_async"):
        generate_game.apply_async(args=[task_id], headers=headers)
    else:
        generate_game.delay(task_id)


def _owned_task(task_id: str, user, db: Session) -> GenerationTask:
    task = db.get(GenerationTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not your task")
    return task


def _ensure_active_task_slot(user_id: str, db: Session) -> None:
    max_active = int(settings.MAX_ACTIVE_TASKS_PER_USER or 0)
    if max_active <= 0:
        return
    active_count = (
        db.query(GenerationTask)
        .filter(
            GenerationTask.user_id == user_id,
            GenerationTask.status.in_([TaskStatus.PENDING, TaskStatus.RUNNING]),
        )
        .count()
    )
    if active_count >= max_active:
        raise HTTPException(status_code=409, detail="TOO_MANY_ACTIVE_TASKS")


def _source_spec_json(source: Game) -> str:
    return json.dumps(
        {
            "title": f"{source.title} Remix",
            "summary": source.summary,
            "genre": source.genre.lower(),
            "theme": "remix",
            "core_loop": source.summary,
            "tags": [tag.name for tag in source.tags[:4]] + ["remix"],
        },
        ensure_ascii=False,
    )


def _source_design_json(source: Game) -> str:
    return json.dumps(
        {
            "archetype": "topdown_collect",
            "source_game": {
                "id": source.id,
                "title": source.title,
                "version": source.current_version,
            },
        },
        ensure_ascii=False,
    )


def _copy_source_task_context(task: GenerationTask, version: GameVersion, source: Game, db: Session) -> None:
    source_task = db.get(GenerationTask, version.source_task_id) if version.source_task_id else None
    task.spec_json = source_task.spec_json if source_task and source_task.spec_json else _source_spec_json(source)
    task.design_json = (
        source_task.design_json if source_task and source_task.design_json else _source_design_json(source)
    )


def _create_remix_task(body: TaskCreateIn, user, db: Session) -> dict:
    if not body.source_game_id:
        raise HTTPException(status_code=422, detail="source_game_id is required for remix tasks")
    source = db.get(Game, body.source_game_id)
    if not source or (source.status != GameStatus.PUBLISHED and source.author_id != user.id):
        raise HTTPException(status_code=404, detail="Source game not found")
    source_version = (
        db.query(GameVersion)
        .filter_by(game_id=source.id, version=source.current_version)
        .first()
    )
    if not source_version:
        raise HTTPException(status_code=409, detail="Source game version is missing")
    if not source_version.manifest_key or not source_version.bundle_key:
        raise HTTPException(status_code=409, detail="Source game artifact metadata is incomplete")

    task = GenerationTask(
        user_id=user.id,
        idea=body.idea,
        task_kind="remix",
        base_game_id=source.id,
        base_version=source.current_version,
        feedback_text=body.idea,
        dimension=body.dimension,
        status=TaskStatus.PENDING,
    )
    _copy_source_task_context(task, source_version, source, db)
    if body.asset_ids:
        task.assets = (
            db.query(Asset)
            .filter(Asset.id.in_(body.asset_ids), Asset.owner_id == user.id)
            .all()
        )
    db.add(task)
    db.commit()
    db.refresh(task)
    _enqueue_generation(task.id)
    return {"task_id": task.id}


@router.post("", dependencies=[Depends(rate_limit(20, 3600, "task_create"))])
def create_task(body: TaskCreateIn, user=Depends(get_current_user), db: Session = Depends(get_db)):
    _ensure_active_task_slot(user.id, db)
    if body.task_kind == "remix":
        return _create_remix_task(body, user, db)
    task = GenerationTask(user_id=user.id, idea=body.idea, status=TaskStatus.PENDING, dimension=body.dimension)
    if body.asset_ids:
        task.assets = (
            db.query(Asset)
            .filter(Asset.id.in_(body.asset_ids), Asset.owner_id == user.id)
            .all()
        )
    db.add(task)
    db.commit()
    db.refresh(task)
    _enqueue_generation(task.id)
    return {"task_id": task.id}


@router.get("")
def list_tasks(user=Depends(get_current_user), db: Session = Depends(get_db)):
    tasks = (
        db.query(GenerationTask)
        .filter_by(user_id=user.id)
        .order_by(GenerationTask.created_at.desc())
        .all()
    )
    # 列表只出轻量 summary（无 logs/steps/design/assets）；详情走 GET /tasks/{id}
    return {"items": [task_out(t, include_details=False) for t in tasks]}


@router.get("/{task_id}")
def get_task(task_id: str, user=Depends(get_current_user), db: Session = Depends(get_db)):
    return task_out(_owned_task(task_id, user, db))


@router.post("/{task_id}/revise", dependencies=[Depends(rate_limit(20, 3600, "task_revise"))])
def revise_task(
    task_id: str,
    body: TaskRevisionIn,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    source = _owned_task(task_id, user, db)
    if source.status != TaskStatus.SUCCEEDED or not source.result_game:
        raise HTTPException(status_code=400, detail="Only a completed preview can be revised")
    game = source.result_game
    if game.status == GameStatus.PUBLISHED:
        raise HTTPException(status_code=400, detail="Published games must be unpublished before revision")
    current_version = next((v for v in game.versions if v.version == game.current_version), None)
    if not current_version or source.version_id != current_version.id:
        raise HTTPException(status_code=409, detail="This task is not the game's current preview version")
    _ensure_active_task_slot(user.id, db)
    active = (
        db.query(GenerationTask)
        .filter(
            GenerationTask.base_game_id == game.id,
            GenerationTask.task_kind == "revision",
            GenerationTask.status.in_([TaskStatus.PENDING, TaskStatus.RUNNING]),
        )
        .first()
    )
    if active:
        raise HTTPException(status_code=409, detail="A revision is already running for this preview")

    feedback = body.feedback.strip()
    revision = GenerationTask(
        user_id=user.id,
        idea=source.idea,
        task_kind="revision",
        base_game_id=game.id,
        base_version=game.current_version,
        result_game_id=game.id,
        feedback_text=feedback,
        dimension=source.dimension or "2d",
        status=TaskStatus.PENDING,
        spec_json=source.spec_json,
        design_json=source.design_json,
    )
    revision.assets = list(source.assets)
    db.add(revision)
    db.commit()
    db.refresh(revision)
    _enqueue_generation(revision.id)
    return {"task_id": revision.id}


@router.post("/{task_id}/retry")
def retry_task(task_id: str, user=Depends(get_current_user), db: Session = Depends(get_db)):
    task = _owned_task(task_id, user, db)
    if task.status != TaskStatus.FAILED:
        raise HTTPException(status_code=400, detail="Only failed tasks can be retried")
    _ensure_active_task_slot(user.id, db)
    for step in list(task.steps):
        db.delete(step)
    task.status = TaskStatus.PENDING
    task.error = None
    task.error_code = None
    task.failed_stage = None
    task.current_step = 0
    task.tokens_used = 0
    task.cost_usd = None
    db.commit()
    _enqueue_generation(task.id)
    return {"task_id": task.id}


@router.post("/{task_id}/cancel")
def cancel_task(task_id: str, user=Depends(get_current_user), db: Session = Depends(get_db)):
    task = _owned_task(task_id, user, db)
    if task.status not in (TaskStatus.PENDING, TaskStatus.RUNNING):
        raise HTTPException(status_code=400, detail="Only active tasks can be cancelled")
    task.status = TaskStatus.CANCELLED
    task.error = "Cancelled by user"
    task.error_code = TaskErrorCode.CANCELLED.value
    task.failed_stage = task.current_agent
    task.finished_at = now_utc()
    db.commit()
    db.refresh(task)
    return task_out(task)


@router.delete("/{task_id}")
def delete_task(task_id: str, user=Depends(get_current_user), db: Session = Depends(get_db)):
    task = _owned_task(task_id, user, db)
    if task.status in (TaskStatus.PENDING, TaskStatus.RUNNING):
        raise HTTPException(status_code=400, detail="Cancel the task before deleting")
    db.delete(task)
    db.commit()
    return {"ok": True}
