import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.api.deps import get_current_user, rate_limit
from app.db.session import SessionLocal, get_db
from app.models import AgentLog, AgentStep, GenerationTask
from app.models.common import TaskStatus
from app.schemas import (
    OkOut,
    TaskCreateIn,
    TaskGeneratedAssetListOut,
    TaskIdOut,
    TaskListOut,
    TaskOut,
    TaskRetryOut,
    TaskRevisionIn,
)
from app.services import task_actions
from app.services.errors import ServiceError
from app.services.serialize import (
    DEFAULT_TASK_LOG_PAGE_SIZE,
    task_event_delta_out,
    task_out,
)
from app.services.task_events import TaskEventsUnavailable, subscribe_task_events
from app.tasks.generate import generate_game

router = APIRouter(prefix="/tasks", tags=["tasks"])
_TERMINAL_TASK_STATUSES = {TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.CANCELLED}


def _run(action):
    try:
        return action()
    except ServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post(
    "",
    response_model=TaskIdOut,
    response_model_exclude_unset=True,
    dependencies=[Depends(rate_limit(20, 3600, "task_create"))],
)
def create_task(body: TaskCreateIn, user=Depends(get_current_user), db: Session = Depends(get_db)):
    task = _run(lambda: task_actions.create_task(db, body, user, queue=generate_game))
    return {"task_id": task.id}


@router.get("", response_model=TaskListOut, response_model_exclude_unset=True)
def list_tasks(
    limit: int = 24,
    offset: int = 0,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tasks, total, offset, limit = task_actions.list_tasks(db, user, limit=limit, offset=offset)
    return {
        "items": [task_out(task, include_details=False) for task in tasks],
        "total": total,
        "has_more": offset + limit < total,
    }


@router.get("/{task_id}", response_model=TaskOut, response_model_exclude_unset=True)
def get_task(
    task_id: str,
    logs_limit: int = Query(DEFAULT_TASK_LOG_PAGE_SIZE, ge=1, le=500),
    logs_before: int | None = Query(None, ge=1),
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    task = _run(lambda: task_actions.get_task(db, task_id, user))
    return task_out(task, logs_limit=logs_limit, logs_before=logs_before)


@router.get(
    "/{task_id}/generated-assets",
    response_model=TaskGeneratedAssetListOut,
    response_model_exclude_unset=True,
)
def get_task_generated_assets(
    task_id: str,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    task = _run(lambda: task_actions.get_task(db, task_id, user))
    from app.agents.checkpoint_reader import checkpoint_values
    from app.services.task_generated_assets import generated_image_previews

    return {"items": generated_image_previews(checkpoint_values(task.id))}


def _serialized_log_cursor(payload: dict | None) -> int:
    """Return only a cursor that is represented by the serialized payload.

    Reading ``MAX(agent_logs.id)`` after serialization creates a lossy window:
    a newly committed log can advance the SSE id without being present in the
    event body, so a reconnect permanently skips it.
    """
    cursor = 0
    for item in (payload or {}).get("logs") or []:
        for entry in item.get("entries") or []:
            try:
                cursor = max(cursor, int(entry.get("cursor") or 0))
            except (TypeError, ValueError, AttributeError):
                continue
    return cursor


def _event_snapshot(task_id: str, user_id: str) -> tuple[str, dict | None, int]:
    db = SessionLocal()
    try:
        task = db.get(GenerationTask, task_id)
        if not task:
            return "missing", None, 0
        if task.user_id != user_id:
            return "forbidden", None, 0
        payload = task_out(task)
        return "ok", payload, _serialized_log_cursor(payload)
    finally:
        db.close()


def _event_delta(
    task_id: str,
    user_id: str,
    after_cursor: int,
) -> tuple[str, dict | None, int]:
    db = SessionLocal()
    try:
        task = db.get(GenerationTask, task_id)
        if not task:
            return "missing", None, after_cursor
        if task.user_id != user_id:
            return "forbidden", None, after_cursor
        rows = (
            db.query(AgentStep, AgentLog)
            .join(AgentLog, AgentLog.step_id == AgentStep.id)
            .filter(
                AgentStep.task_id == task_id,
                AgentLog.id > max(0, int(after_cursor)),
            )
            .order_by(AgentLog.id)
            .all()
        )
        cursor = int(rows[-1][1].id) if rows else max(0, int(after_cursor))
        return "ok", task_event_delta_out(task, rows, cursor), cursor
    finally:
        db.close()


def _event_cursor(raw: str | None) -> int | None:
    if not raw:
        return None
    try:
        value = int(raw.strip())
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


def _sse(event: str, data: dict, *, event_id: str | None = None) -> str:
    lines = []
    if event_id:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event}")
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    lines.extend(f"data: {line}" for line in payload.splitlines() or [""])
    return "\n".join(lines) + "\n\n"


@router.get(
    "/{task_id}/events",
    responses={200: {"content": {"text/event-stream": {}}}},
)
async def stream_task_events(
    task_id: str,
    request: Request,
    user=Depends(get_current_user),
):
    resume_cursor = _event_cursor(request.headers.get("last-event-id"))
    initial_event = "task" if resume_cursor is None else "task_delta"
    initial_loader = _event_snapshot if resume_cursor is None else _event_delta
    initial_args = (
        (task_id, user.id)
        if resume_cursor is None
        else (task_id, user.id, resume_cursor)
    )
    state, initial, initial_cursor = await run_in_threadpool(initial_loader, *initial_args)
    if state == "missing":
        raise HTTPException(status_code=404, detail="Task not found")
    if state == "forbidden":
        raise HTTPException(status_code=403, detail="Not your task")

    async def event_stream():
        initial_payload = initial or {}
        snapshot = (
            initial_payload
            if initial_event == "task"
            else initial_payload.get("task") or {}
        )
        yield "retry: 3000\n\n"
        cursor = initial_cursor
        last_summary = json.dumps(
            snapshot, ensure_ascii=False, sort_keys=True, default=str
        )
        yield _sse(initial_event, initial_payload, event_id=str(cursor))
        if snapshot.get("status") in _TERMINAL_TASK_STATUSES:
            return
        try:
            async for signal in subscribe_task_events(task_id):
                if await request.is_disconnected():
                    return
                if signal is None:
                    yield ": keep-alive\n\n"
                    continue
                current_state, current, next_cursor = await run_in_threadpool(
                    _event_delta,
                    task_id,
                    user.id,
                    cursor,
                )
                if current_state == "missing":
                    yield _sse("deleted", {"task_id": task_id}, event_id=str(cursor))
                    return
                if current_state != "ok" or current is None:
                    return
                summary = current.get("task") or {}
                summary_serialized = json.dumps(
                    summary,
                    ensure_ascii=False,
                    sort_keys=True,
                    default=str,
                )
                if not current.get("logs") and summary_serialized == last_summary:
                    continue
                cursor = next_cursor
                last_summary = summary_serialized
                yield _sse("task_delta", current, event_id=str(cursor))
                if summary.get("status") in _TERMINAL_TASK_STATUSES:
                    return
        except TaskEventsUnavailable:
            yield _sse("unavailable", {"retry_in_ms": 5000})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post(
    "/{task_id}/revise",
    response_model=TaskIdOut,
    response_model_exclude_unset=True,
    dependencies=[Depends(rate_limit(20, 3600, "task_revise"))],
)
def revise_task(
    task_id: str,
    body: TaskRevisionIn,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    revision = _run(lambda: task_actions.revise_task(db, task_id, body, user, queue=generate_game))
    return {"task_id": revision.id}


@router.post("/{task_id}/retry", response_model=TaskRetryOut, response_model_exclude_unset=True)
def retry_task(
    task_id: str,
    from_scratch: bool = False,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    task, mode = _run(
        lambda: task_actions.retry_task(
            db,
            task_id,
            user,
            from_scratch=from_scratch,
            queue=generate_game,
        )
    )
    return {"task_id": task.id, "mode": mode}


@router.post("/{task_id}/cancel", response_model=TaskOut, response_model_exclude_unset=True)
def cancel_task(task_id: str, user=Depends(get_current_user), db: Session = Depends(get_db)):
    task = _run(lambda: task_actions.cancel_task(db, task_id, user))
    return task_out(task)


@router.delete("/{task_id}", response_model=OkOut, response_model_exclude_unset=True)
def delete_task(task_id: str, user=Depends(get_current_user), db: Session = Depends(get_db)):
    _run(lambda: task_actions.delete_task(db, task_id, user))
    return {"ok": True}
