import logging
from contextlib import contextmanager
from hashlib import blake2b

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.agents.pipeline import run_generation
from app.core.checkpointing import CheckpointStorageError
from app.core.config import settings
from app.core.telemetry import clear_context
from app.db.session import SessionLocal, engine
from app.models import GenerationTask
from app.models.common import TaskStatus
from app.tasks.celery_app import celery

logger = logging.getLogger(__name__)


def _generation_lock_key(task_id: str) -> int:
    digest = blake2b(
        f"generation_execution:{task_id}".encode("utf-8"), digest_size=8
    ).digest()
    return int.from_bytes(digest, byteorder="big", signed=True)


def _dispatch_is_current(task_id: str, dispatch_generation: int) -> bool:
    db = SessionLocal()
    try:
        task = db.get(GenerationTask, task_id)
        return bool(
            task
            and task.status in (TaskStatus.PENDING, TaskStatus.RUNNING)
            and task.dispatch_generation == dispatch_generation
        )
    finally:
        db.close()


def _message_dispatch_generation(task, explicit_generation: int | None) -> int:
    if explicit_generation is not None:
        return int(explicit_generation)
    headers = getattr(getattr(task, "request", None), "headers", None) or {}
    return int(headers.get("dispatch_generation", 0))


@contextmanager
def generation_execution_lock(task_id: str):
    """Hold a PostgreSQL session lock for the complete generation execution."""

    if engine.dialect.name != "postgresql":
        yield True
        return

    connection = engine.connect()
    acquired = False
    lock_key = _generation_lock_key(task_id)
    try:
        acquired = bool(
            connection.execute(
                text("SELECT pg_try_advisory_lock(:lock_key)"),
                {"lock_key": lock_key},
            ).scalar_one()
        )
        # Session-level advisory locks survive COMMIT. End the implicit SELECT
        # transaction so a long generation does not sit idle-in-transaction.
        connection.commit()
        try:
            yield acquired
        finally:
            if acquired:
                try:
                    unlocked = bool(
                        connection.execute(
                            text("SELECT pg_advisory_unlock(:lock_key)"),
                            {"lock_key": lock_key},
                        ).scalar_one()
                    )
                    connection.commit()
                except Exception:  # noqa: BLE001 - invalidate is the safe fallback
                    connection.invalidate()
                    acquired = False
                    logger.exception("failed to release generation advisory lock")
                else:
                    if unlocked:
                        acquired = False
                    else:
                        connection.invalidate()
                        acquired = False
                        logger.error(
                            "generation advisory lock was not held during unlock"
                        )
    finally:
        if acquired:
            # A failed explicit unlock must not return a locked connection to the pool.
            connection.invalidate()
        connection.close()


def _execute_generation_delivery(
    task,
    task_id: str,
    dispatch_generation: int | None,
) -> None:
    try:
        expected_generation = _message_dispatch_generation(task, dispatch_generation)
    except (TypeError, ValueError):
        return
    try:
        if not _dispatch_is_current(task_id, expected_generation):
            return

        with generation_execution_lock(task_id) as acquired:
            if not acquired:
                raise task.retry(
                    countdown=settings.GENERATION_LOCK_RETRY_SECONDS,
                    max_retries=None,
                )
            # The task may have been cancelled/retried while this delivery waited for the lock.
            if not _dispatch_is_current(task_id, expected_generation):
                return
            run_generation(task_id, expected_dispatch_generation=expected_generation)
    except (SQLAlchemyError, CheckpointStorageError) as exc:
        # The outbox event is already marked published; retry transient DB failures
        # (including checkpoint storage) so a brief outage cannot strand a task.
        raise task.retry(
            exc=exc,
            countdown=settings.GENERATION_LOCK_RETRY_SECONDS,
            max_retries=None,
        ) from exc
    finally:
        clear_context()


# New dispatches use a versioned queue. Workers from the previous release only
# consume the default queue, so they cannot execute v2 messages during a rolling deploy.
@celery.task(
    bind=True,
    name="generate_game_v2",
    soft_time_limit=settings.GENERATION_TASK_SOFT_TIME_LIMIT,
    time_limit=settings.GENERATION_TASK_TIME_LIMIT,
    max_retries=None,
)
def generate_game(self, task_id: str, dispatch_generation: int | None = None) -> None:
    _execute_generation_delivery(self, task_id, dispatch_generation)


# Keep consuming messages emitted by the old API while a deployment is in flight.
@celery.task(
    bind=True,
    name="generate_game",
    soft_time_limit=settings.GENERATION_TASK_SOFT_TIME_LIMIT,
    time_limit=settings.GENERATION_TASK_TIME_LIMIT,
    max_retries=None,
)
def generate_game_legacy(
    self, task_id: str, dispatch_generation: int | None = None
) -> None:
    _execute_generation_delivery(self, task_id, dispatch_generation)
