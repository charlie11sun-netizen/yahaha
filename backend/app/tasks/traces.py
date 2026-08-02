from datetime import timedelta

from app.core.config import settings
from app.db.session import SessionLocal
from app.models import AgentTraceEvent
from app.models.common import now_utc
from app.tasks.celery_app import celery

_PURGE_BATCH_SIZE = 5_000


@celery.task(name="purge_expired_agent_traces", ignore_result=True)
def purge_expired_agent_traces() -> int:
    """Delete detailed trace events beyond the configured retention window."""
    cutoff = now_utc() - timedelta(days=settings.CODE_AGENT_TRACE_RETENTION_DAYS)
    deleted = 0
    db = SessionLocal()
    try:
        while True:
            event_ids = [
                row[0]
                for row in db.query(AgentTraceEvent.id)
                .filter(AgentTraceEvent.created_at < cutoff)
                .order_by(AgentTraceEvent.created_at)
                .limit(_PURGE_BATCH_SIZE)
                .all()
            ]
            if not event_ids:
                return deleted
            deleted += (
                db.query(AgentTraceEvent)
                .filter(AgentTraceEvent.id.in_(event_ids))
                .delete(synchronize_session=False)
            )
            db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
