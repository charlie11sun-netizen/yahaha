import json
import logging
from hashlib import blake2b

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.checkpointing import checkpoint_exists, delete_checkpoint_thread
from app.core.errors import TaskErrorCode
from app.models import Asset, Game, GameVersion, GenerationTask
from app.models.common import GameStatus, TaskStatus, now_utc
from app.schemas import TaskCreateIn, TaskRevisionIn
from app.services.errors import ServiceError
from app.services.pagination import normalize_pagination
from app.services.task_dispatch import (
    QueueTaskDispatcher,
    dispatch_generation_event,
    stage_generation_dispatch,
)
from app.services.task_events import publish_task_event


ACTIVE_TASK_STATUSES = (TaskStatus.PENDING, TaskStatus.RUNNING)
logger = logging.getLogger(__name__)


def _commit_and_dispatch(db: Session, task: GenerationTask, queue) -> GenerationTask:
    """Atomically commit task state and its dispatch intent, then publish best-effort."""

    event = stage_generation_dispatch(db, task)
    db.commit()
    db.refresh(task)
    publish_task_event(task.id, "dispatched")
    try:
        dispatch_generation_event(db, event.id, QueueTaskDispatcher(queue))
    except Exception:  # noqa: BLE001 - the durable row lets a later scanner recover
        db.rollback()
        logger.exception(
            "immediate generation dispatch failed unexpectedly; outbox scanner will retry",
            extra={"event_id": event.id, "generation_task_id": task.id},
        )
    return task


def owned_task(db: Session, task_id: str, user) -> GenerationTask:
    task = db.get(GenerationTask, task_id)
    if not task:
        raise ServiceError(404, "Task not found")
    if task.user_id != user.id:
        raise ServiceError(403, "Not your task")
    return task


def _advisory_lock_key(namespace: str, identity: str) -> int:
    digest = blake2b(f"{namespace}:{identity}".encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, byteorder="big", signed=True)


def _acquire_advisory_xact_lock(db: Session, namespace: str, identity: str) -> None:
    bind = db.get_bind()
    if bind.dialect.name != "postgresql":
        return
    db.execute(
        text("SELECT pg_advisory_xact_lock(:lock_key)"),
        {"lock_key": _advisory_lock_key(namespace, identity)},
    )


def ensure_active_task_slot(db: Session, user_id: str) -> None:
    max_active = int(settings.MAX_ACTIVE_TASKS_PER_USER or 0)
    if max_active <= 0:
        return
    _acquire_advisory_xact_lock(db, "task_active_user", user_id)
    active_count = (
        db.query(GenerationTask)
        .filter(
            GenerationTask.user_id == user_id,
            GenerationTask.status.in_(ACTIVE_TASK_STATUSES),
        )
        .count()
    )
    if active_count >= max_active:
        raise ServiceError(409, "TOO_MANY_ACTIVE_TASKS")


def ensure_no_active_revision(db: Session, game_id: str) -> None:
    _acquire_advisory_xact_lock(db, "task_revision_game", game_id)
    active = (
        db.query(GenerationTask)
        .filter(
            GenerationTask.base_game_id == game_id,
            GenerationTask.task_kind == "revision",
            GenerationTask.status.in_(ACTIVE_TASK_STATUSES),
        )
        .first()
    )
    if active:
        raise ServiceError(409, "A revision is already running for this preview")


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
    task.design_json = source_task.design_json if source_task and source_task.design_json else _source_design_json(source)


def _attach_owned_assets(db: Session, task: GenerationTask, user_id: str, asset_ids: list[str] | None) -> None:
    if asset_ids:
        task.assets = db.query(Asset).filter(Asset.id.in_(asset_ids), Asset.owner_id == user_id).all()


def _create_remix_task(db: Session, body: TaskCreateIn, user) -> GenerationTask:
    if not body.source_game_id:
        raise ServiceError(422, "source_game_id is required for remix tasks")
    source = db.get(Game, body.source_game_id)
    if not source or (source.status != GameStatus.PUBLISHED and source.author_id != user.id):
        raise ServiceError(404, "Source game not found")
    source_version = db.query(GameVersion).filter_by(game_id=source.id, version=source.current_version).first()
    if not source_version:
        raise ServiceError(409, "Source game version is missing")
    if not source_version.manifest_key or not source_version.bundle_key:
        raise ServiceError(409, "Source game artifact metadata is incomplete")

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
    _attach_owned_assets(db, task, user.id, body.asset_ids)
    db.add(task)
    return task


def create_task(db: Session, body: TaskCreateIn, user, *, queue) -> GenerationTask:
    ensure_active_task_slot(db, user.id)
    if body.task_kind == "remix":
        task = _create_remix_task(db, body, user)
    else:
        task = GenerationTask(user_id=user.id, idea=body.idea, status=TaskStatus.PENDING, dimension=body.dimension)
        _attach_owned_assets(db, task, user.id, body.asset_ids)
        db.add(task)
    return _commit_and_dispatch(db, task, queue)


def list_tasks(db: Session, user, *, limit: int = 24, offset: int = 0) -> tuple[list[GenerationTask], int, int, int]:
    limit, offset = normalize_pagination(limit, offset)
    query = db.query(GenerationTask).filter_by(user_id=user.id)
    total = query.count()
    page = query.order_by(GenerationTask.created_at.desc()).offset(offset).limit(limit).all()
    return page, total, offset, limit


def get_task(db: Session, task_id: str, user) -> GenerationTask:
    return owned_task(db, task_id, user)


def revise_task(db: Session, task_id: str, body: TaskRevisionIn, user, *, queue) -> GenerationTask:
    source = owned_task(db, task_id, user)
    if source.status != TaskStatus.SUCCEEDED or not source.result_game:
        raise ServiceError(400, "Only a completed preview can be revised")
    game = source.result_game
    if game.status == GameStatus.PUBLISHED:
        raise ServiceError(400, "Published games must be unpublished before revision")
    current_version = next((version for version in game.versions if version.version == game.current_version), None)
    if not current_version or source.version_id != current_version.id:
        raise ServiceError(409, "This task is not the game's current preview version")

    ensure_active_task_slot(db, user.id)
    ensure_no_active_revision(db, game.id)

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
    return _commit_and_dispatch(db, revision, queue)


def retry_task(db: Session, task_id: str, user, *, from_scratch: bool = False, queue) -> tuple[GenerationTask, str]:
    task = owned_task(db, task_id, user)
    if task.status != TaskStatus.FAILED:
        raise ServiceError(400, "Only failed tasks can be retried")
    ensure_active_task_slot(db, user.id)

    # Another retry request may have loaded the same FAILED row before waiting
    # on the per-user quota lock. Re-read it under a row lock so stale identity-map
    # state cannot stage the same dispatch_generation twice.
    task = (
        db.query(GenerationTask)
        .filter(GenerationTask.id == task_id)
        .populate_existing()
        .with_for_update(of=GenerationTask)
        .one_or_none()
    )
    if not task:
        raise ServiceError(404, "Task not found")
    if task.user_id != user.id:
        raise ServiceError(403, "Not your task")
    if task.status != TaskStatus.FAILED:
        raise ServiceError(400, "Only failed tasks can be retried")

    can_resume = not from_scratch and checkpoint_exists(task.id)
    if not can_resume:
        # A restart must not accidentally append fresh input to an old native
        # thread. This also cleans up incomplete pre-migration checkpoint rows.
        delete_checkpoint_thread(task.id)
        for step in list(task.steps):
            db.delete(step)
        task.current_step = 0
        task.tokens_used = 0
        task.cost_usd = None
        mode = "restart"
    else:
        mode = "resume"

    task.repair_attempts = 0
    task.replan_attempts = 0
    task.status = TaskStatus.PENDING
    task.error = None
    task.error_code = None
    task.failed_stage = None
    task.finished_at = None
    return _commit_and_dispatch(db, task, queue), mode


def cancel_task(db: Session, task_id: str, user) -> GenerationTask:
    task = owned_task(db, task_id, user)
    if task.status not in (TaskStatus.PENDING, TaskStatus.RUNNING):
        raise ServiceError(400, "Only active tasks can be cancelled")
    task.status = TaskStatus.CANCELLED
    task.error = "Cancelled by user"
    task.error_code = TaskErrorCode.CANCELLED.value
    task.failed_stage = task.current_agent
    task.finished_at = now_utc()
    db.commit()
    db.refresh(task)
    publish_task_event(task.id, "cancelled")
    try:
        # A crashed worker may no longer be present to run pipeline finalization.
        delete_checkpoint_thread(task.id)
    except Exception:  # noqa: BLE001 - cancellation already committed
        logger.exception("failed to delete cancelled task checkpoint", extra={"generation_task_id": task.id})
    return task


def delete_task(db: Session, task_id: str, user) -> None:
    task = owned_task(db, task_id, user)
    if task.status in (TaskStatus.PENDING, TaskStatus.RUNNING):
        raise ServiceError(400, "Cancel the task before deleting")
    delete_checkpoint_thread(task.id)
    deleted_task_id = task.id
    db.delete(task)
    db.commit()
    publish_task_event(deleted_task_id, "deleted")
