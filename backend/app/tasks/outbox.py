from app.core.config import settings
from app.db.session import SessionLocal
from app.services.task_dispatch import (
    QueueTaskDispatcher,
    dispatch_pending_generation_events,
)
from app.tasks.celery_app import celery
from app.tasks.generate import generate_game


@celery.task(name="dispatch_generation_outbox", ignore_result=True)
def dispatch_generation_outbox() -> int:
    db = SessionLocal()
    try:
        return dispatch_pending_generation_events(
            db,
            QueueTaskDispatcher(generate_game),
            limit=settings.GENERATION_OUTBOX_BATCH_SIZE,
            republish_after_seconds=max(
                settings.CELERY_VISIBILITY_TIMEOUT,
                settings.GENERATION_TASK_TIME_LIMIT + 60,
            ),
        )
    finally:
        db.close()
