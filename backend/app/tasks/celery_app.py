from celery import Celery

from app.core.config import settings

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
    beat_schedule={
        "purge-expired-memories-daily": {
            "task": "purge_expired_memories",
            "schedule": 24 * 60 * 60,
        },
    },
)
