"""Reliable generation-task dispatch backed by a transactional outbox."""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.core.telemetry import current_request_id
from app.models import GenerationDispatchOutbox, GenerationTask
from app.models.common import TaskStatus, now_utc

logger = logging.getLogger(__name__)


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class GenerationDispatchMessage:
    event_id: str
    task_id: str
    dispatch_generation: int
    request_id: str


class TaskDispatcher(Protocol):
    def dispatch(self, message: GenerationDispatchMessage) -> None: ...


class QueueTaskDispatcher:
    """Adapter for a Celery task (and the lightweight delay-only test double)."""

    def __init__(self, queue) -> None:
        self._queue = queue

    def dispatch(self, message: GenerationDispatchMessage) -> None:
        if hasattr(self._queue, "apply_async"):
            self._queue.apply_async(
                # Generation lives in a header while the v2 task is isolated on
                # generation-v2; the payload itself remains one-argument compatible.
                args=[message.task_id],
                task_id=message.event_id,
                headers={
                    "request_id": message.request_id,
                    "dispatch_generation": message.dispatch_generation,
                },
            )
        else:
            self._queue.delay(message.task_id, message.dispatch_generation)


def stage_generation_dispatch(
    db: Session,
    task: GenerationTask,
    *,
    request_id: str | None = None,
) -> GenerationDispatchOutbox:
    """Stage a new dispatch in the caller's task-write transaction."""

    task.dispatch_generation = int(task.dispatch_generation or 0) + 1
    db.add(task)
    db.flush()
    event = GenerationDispatchOutbox(
        task_id=task.id,
        dispatch_generation=task.dispatch_generation,
        request_id=(
            request_id if request_id is not None else current_request_id() or ""
        )[:128],
        available_at=now_utc(),
    )
    db.add(event)
    db.flush()
    return event


def _retry_delay(attempts: int) -> timedelta:
    # 5s, 10s, 20s ... capped at five minutes.
    return timedelta(seconds=min(300, 5 * (2 ** min(max(attempts - 1, 0), 6))))


def dispatch_generation_event(
    db: Session,
    event_id: str,
    dispatcher: TaskDispatcher,
    *,
    republish_before: datetime | None = None,
) -> bool:
    """Publish one due event; stale active deliveries may be published again."""

    event = (
        db.query(GenerationDispatchOutbox)
        .filter(GenerationDispatchOutbox.id == event_id)
        .with_for_update(skip_locked=True)
        .one_or_none()
    )
    if event is None:
        db.commit()
        return False

    attempted_at = now_utc()
    if _utc(event.available_at) > attempted_at:
        db.commit()
        return False

    if event.published_at is not None:
        task = db.get(GenerationTask, event.task_id)
        can_republish = bool(
            republish_before is not None
            and _utc(event.published_at) <= _utc(republish_before)
            and task
            and task.status in (TaskStatus.PENDING, TaskStatus.RUNNING)
            and task.dispatch_generation == event.dispatch_generation
        )
        if not can_republish:
            db.commit()
            return False

    event.attempts += 1
    event.last_attempt_at = attempted_at
    message = GenerationDispatchMessage(
        event_id=event.id,
        task_id=event.task_id,
        dispatch_generation=event.dispatch_generation,
        request_id=event.request_id,
    )
    try:
        dispatcher.dispatch(message)
    except Exception as exc:  # noqa: BLE001
        # Broker clients expose multiple unrelated transport exception types.
        event.last_error = str(exc)[:4000]
        event.available_at = attempted_at + _retry_delay(event.attempts)
        db.commit()
        logger.warning(
            "generation dispatch failed; outbox event will be retried",
            extra={"event_id": event.id, "generation_task_id": event.task_id},
        )
        return False

    event.published_at = attempted_at
    event.available_at = attempted_at
    event.last_error = None
    db.commit()
    return True


def dispatch_pending_generation_events(
    db: Session,
    dispatcher: TaskDispatcher,
    *,
    limit: int = 100,
    republish_after_seconds: int | None = None,
) -> int:
    """Publish a bounded batch of due or stale-active outbox events."""

    scan_time = now_utc()
    due = and_(
        GenerationDispatchOutbox.published_at.is_(None),
        GenerationDispatchOutbox.available_at <= scan_time,
    )
    republish_before = None
    query = db.query(GenerationDispatchOutbox.id).join(
        GenerationTask,
        GenerationTask.id == GenerationDispatchOutbox.task_id,
    )
    if republish_after_seconds is not None:
        republish_before = scan_time - timedelta(
            seconds=max(60, republish_after_seconds)
        )
        due = or_(
            due,
            and_(
                GenerationDispatchOutbox.published_at <= republish_before,
                GenerationDispatchOutbox.available_at <= scan_time,
                GenerationDispatchOutbox.dispatch_generation
                == GenerationTask.dispatch_generation,
                GenerationTask.status.in_((TaskStatus.PENDING, TaskStatus.RUNNING)),
            ),
        )

    due_ids = [
        event_id
        for (event_id,) in (
            query.filter(due)
            .order_by(
                GenerationDispatchOutbox.available_at,
                GenerationDispatchOutbox.created_at,
            )
            .limit(max(1, limit))
            .all()
        )
    ]
    published = 0
    for event_id in due_ids:
        published += int(
            dispatch_generation_event(
                db,
                event_id,
                dispatcher,
                republish_before=republish_before,
            )
        )
    return published
