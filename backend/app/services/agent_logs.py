"""Shared durable append path for live agent step logs."""

import json
import logging
import time
from collections.abc import Callable
from typing import Any

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError, OperationalError

from app.models import AgentLog, AgentStep


def _payload_json(payload: dict | None) -> str | None:
    if payload is None:
        return None
    try:
        return json.dumps(payload, ensure_ascii=False, default=str)
    except Exception:  # noqa: BLE001
        return None


def append_agent_log(
    line: str,
    *,
    step_id: str | None,
    payload: dict | None = None,
    level: str = "info",
    task_id: str | None = None,
    session_factory: Callable[[], Any],
    publish_task_event: Callable[[str, str], Any],
    logger: logging.Logger,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    """Append one log row with serialized-step locking and bounded retries."""
    if not step_id:
        return False

    last_error: Exception | None = None
    for attempt in range(3):
        db = session_factory()
        committed_task_id: str | None = None
        try:
            # PostgreSQL serializes writers on the parent step row. SQLite
            # ignores FOR UPDATE, so the unique constraint plus retry is its
            # concurrency fallback.
            step = (
                db.query(AgentStep)
                .filter(AgentStep.id == step_id)
                .with_for_update()
                .one_or_none()
            )
            if step is None:
                return False
            latest_seq = (
                db.query(func.max(AgentLog.seq))
                .filter(AgentLog.step_id == step_id)
                .scalar()
            )
            db.add(
                AgentLog(
                    step_id=step_id,
                    seq=int(latest_seq) + 1 if latest_seq is not None else 0,
                    line=str(line),
                    level=level,
                    payload_json=_payload_json(payload),
                )
            )
            db.commit()
            committed_task_id = task_id or step.task_id
        except IntegrityError as exc:
            db.rollback()
            last_error = exc
        except OperationalError as exc:
            db.rollback()
            if "locked" not in str(exc).lower():
                logger.exception("agent log write failed")
                return False
            last_error = exc
        except Exception:  # noqa: BLE001
            db.rollback()
            logger.exception("agent log write failed")
            return False
        finally:
            db.close()

        if committed_task_id:
            publish_task_event(committed_task_id, "log_appended")
            return True
        if attempt < 2:
            sleep(0.01 * (attempt + 1))

    if last_error is not None:
        logger.warning("agent log write exhausted retries: %s", last_error)
    return False


__all__ = ["append_agent_log"]
