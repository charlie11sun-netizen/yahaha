import json

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import TaskErrorCode
from app.core.telemetry import current_request_id
from app.models import Asset, Game, GameVersion, GenerationTask
from app.models.common import GameStatus, TaskStatus, now_utc
from app.schemas import TaskCreateIn, TaskRevisionIn
from app.services.errors import ServiceError


def enqueue_generation(task_id: str, queue) -> None:
    headers = {"request_id": current_request_id() or ""}
    if hasattr(queue, "apply_async"):
        queue.apply_async(args=[task_id], headers=headers)
    else:
        queue.delay(task_id)


def owned_task(db: Session, task_id: str, user) -> GenerationTask:
    task = db.get(GenerationTask, task_id)
    if not task:
        raise ServiceError(404, "Task not found")
    if task.user_id != user.id:
        raise ServiceError(403, "Not your task")
    return task


def ensure_active_task_slot(db: Session, user_id: str) -> None:
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
        raise ServiceError(409, "TOO_MANY_ACTIVE_TASKS")


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
    db.commit()
    db.refresh(task)
    return task


def create_task(db: Session, body: TaskCreateIn, user, *, queue) -> GenerationTask:
    ensure_active_task_slot(db, user.id)
    if body.task_kind == "remix":
        task = _create_remix_task(db, body, user)
    else:
        task = GenerationTask(user_id=user.id, idea=body.idea, status=TaskStatus.PENDING, dimension=body.dimension)
        _attach_owned_assets(db, task, user.id, body.asset_ids)
        db.add(task)
        db.commit()
        db.refresh(task)
    enqueue_generation(task.id, queue)
    return task


def list_tasks(db: Session, user) -> list[GenerationTask]:
    return (
        db.query(GenerationTask)
        .filter_by(user_id=user.id)
        .order_by(GenerationTask.created_at.desc())
        .all()
    )


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
        raise ServiceError(409, "A revision is already running for this preview")

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
    enqueue_generation(revision.id, queue)
    return revision


def _resume_payload(task: GenerationTask, *, from_scratch: bool) -> dict | None:
    if from_scratch or not task.state_json:
        return None
    try:
        payload = json.loads(task.state_json)
    except Exception:  # noqa: BLE001
        return None
    if isinstance(payload, dict) and isinstance(payload.get("node"), str) and isinstance(payload.get("state"), dict):
        return payload
    return None


def retry_task(db: Session, task_id: str, user, *, from_scratch: bool = False, queue) -> tuple[GenerationTask, str]:
    task = owned_task(db, task_id, user)
    if task.status != TaskStatus.FAILED:
        raise ServiceError(400, "Only failed tasks can be retried")
    ensure_active_task_slot(db, user.id)

    resume_payload = _resume_payload(task, from_scratch=from_scratch)
    if resume_payload is None:
        for step in list(task.steps):
            db.delete(step)
        task.current_step = 0
        task.tokens_used = 0
        task.cost_usd = None
        task.state_json = None
        mode = "restart"
    else:
        state = resume_payload["state"]
        for key in ("repair_attempts", "replan_attempts", "gameplay_repair_attempts"):
            state[key] = 0
        for key in ("last_error", "error_code", "error_message"):
            state.pop(key, None)
        state["status"] = "running"
        task.state_json = json.dumps(resume_payload, ensure_ascii=False)
        mode = "resume"

    task.repair_attempts = 0
    task.replan_attempts = 0
    task.status = TaskStatus.PENDING
    task.error = None
    task.error_code = None
    task.failed_stage = None
    task.finished_at = None
    db.commit()
    enqueue_generation(task.id, queue)
    return task, mode


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
    return task


def delete_task(db: Session, task_id: str, user) -> None:
    task = owned_task(db, task_id, user)
    if task.status in (TaskStatus.PENDING, TaskStatus.RUNNING):
        raise ServiceError(400, "Cancel the task before deleting")
    db.delete(task)
    db.commit()
