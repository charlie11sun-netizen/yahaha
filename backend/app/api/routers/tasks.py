import json
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.api.deps import get_current_user, rate_limit
from app.db.session import SessionLocal, get_db
from app.models import GenerationTask
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
from app.services.serialize import task_out
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
def get_task(task_id: str, user=Depends(get_current_user), db: Session = Depends(get_db)):
    task = _run(lambda: task_actions.get_task(db, task_id, user))
    return task_out(task)


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
    from app.services.task_generated_assets import generated_image_previews

    return {"items": generated_image_previews(task.id)}


def _event_snapshot(task_id: str, user_id: str) -> tuple[str, dict | None]:
    db = SessionLocal()
    try:
        task = db.get(GenerationTask, task_id)
        if not task:
            return "missing", None
        if task.user_id != user_id:
            return "forbidden", None
        return "ok", task_out(task)
    finally:
        db.close()


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
    state, initial = await run_in_threadpool(_event_snapshot, task_id, user.id)
    if state == "missing":
        raise HTTPException(status_code=404, detail="Task not found")
    if state == "forbidden":
        raise HTTPException(status_code=403, detail="Not your task")

    async def event_stream():
        snapshot = initial or {}
        serialized = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, default=str)
        yield "retry: 3000\n\n"
        yield _sse("task", snapshot, event_id=str(time.time_ns()))
        if snapshot.get("status") in _TERMINAL_TASK_STATUSES:
            return
        try:
            async for signal in subscribe_task_events(task_id):
                if await request.is_disconnected():
                    return
                if signal is None:
                    yield ": keep-alive\n\n"
                    continue
                current_state, current = await run_in_threadpool(
                    _event_snapshot,
                    task_id,
                    user.id,
                )
                if current_state == "missing":
                    yield _sse("deleted", {"task_id": task_id})
                    return
                if current_state != "ok" or current is None:
                    return
                current_serialized = json.dumps(
                    current,
                    ensure_ascii=False,
                    sort_keys=True,
                    default=str,
                )
                if current_serialized == serialized:
                    continue
                serialized = current_serialized
                yield _sse("task", current, event_id=str(time.time_ns()))
                if current.get("status") in _TERMINAL_TASK_STATUSES:
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
