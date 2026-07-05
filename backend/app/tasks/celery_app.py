from celery import Celery
from celery.signals import task_postrun, task_prerun

from app.core.config import settings
from app.core.telemetry import bind_context, clear_context, configure_logging, init_otel, init_sentry

configure_logging()
init_sentry("gameweave-worker")

celery = Celery(
    "gameweave",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["app.tasks.generate", "app.tasks.memory"],
)
celery.conf.update(
    task_acks_late=True,
    task_track_started=True,
    worker_prefetch_multiplier=1,
    worker_max_memory_per_child=settings.WORKER_MAX_MEMORY_PER_CHILD,
    # Must be greater than generate_game's hard time limit. With acks_late,
    # Redis can redeliver a still-running task after visibility_timeout.
    broker_transport_options={"visibility_timeout": settings.CELERY_VISIBILITY_TIMEOUT},
    beat_schedule={
        "purge-expired-memories-daily": {
            "task": "purge_expired_memories",
            "schedule": 24 * 60 * 60,
        },
    },
)
init_otel(service_name="gameweave-worker")


@task_prerun.connect
def _bind_task_context(task_id=None, task=None, args=None, **_kwargs):
    headers = getattr(getattr(task, "request", None), "headers", None) or {}
    generation_task_id = str(args[0]) if args else None
    bind_context(
        request_id=headers.get("request_id") or headers.get("x-request-id") or str(task_id or ""),
        task_id=generation_task_id,
    )


@task_postrun.connect
def _clear_task_context(**_kwargs):
    clear_context()
