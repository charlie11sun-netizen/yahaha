from app.db.session import SessionLocal
from app.models import MemorySettings
from app.services.memory import purge_expired_memories as purge_user_memories
from app.tasks.celery_app import celery


@celery.task(name="purge_expired_memories")
def purge_expired_memories() -> int:
    """Enforce user retention windows even when an account is inactive."""
    db = SessionLocal()
    try:
        user_ids = [
            row[0]
            for row in db.query(MemorySettings.user_id)
            .filter(MemorySettings.retention_days.isnot(None))
            .all()
        ]
        deleted = sum(purge_user_memories(db, user_id) for user_id in user_ids)
        db.commit()
        return deleted
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
