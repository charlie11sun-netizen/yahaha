"""LangGraph checkpoint storage shared by API and generation workers.

Production uses the same PostgreSQL database as the application. Tests run on
SQLite and use one process-local LangGraph saver so retry requests and worker
execution still observe the same checkpoint thread.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from threading import Lock
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.engine import make_url

from app.core.config import settings


_memory_saver = InMemorySaver()
_setup_lock = Lock()
_postgres_ready = False
_POSTGRES_SETUP_LOCK_KEY = 469_163_091_462_259_662


class CheckpointStorageError(RuntimeError):
    """The durable checkpoint backend is temporarily unavailable."""


def checkpoint_config(task_id: str, checkpoint_id: str | None = None) -> dict[str, Any]:
    configurable = {"thread_id": task_id}
    if checkpoint_id:
        configurable["checkpoint_id"] = checkpoint_id
    return {"configurable": configurable}


def _postgres_connection_string() -> str:
    url = make_url(settings.DATABASE_URL)
    if url.get_backend_name() != "postgresql":
        raise RuntimeError("LangGraph PostgresSaver requires a PostgreSQL DATABASE_URL")
    return url.set(drivername="postgresql").render_as_string(hide_password=False)


def _setup_postgres_saver(saver: Any) -> None:
    global _postgres_ready
    if _postgres_ready:
        return
    with _setup_lock:
        if _postgres_ready:
            return
        saver.conn.execute(
            "SELECT pg_advisory_lock(%s)",
            (_POSTGRES_SETUP_LOCK_KEY,),
        )
        try:
            saver.setup()
        finally:
            saver.conn.execute(
                "SELECT pg_advisory_unlock(%s)",
                (_POSTGRES_SETUP_LOCK_KEY,),
            )
        _postgres_ready = True


def setup_checkpointer() -> None:
    """Apply LangGraph's PostgreSQL schema before API and worker startup."""

    if make_url(settings.DATABASE_URL).get_backend_name() != "postgresql":
        return

    from langgraph.checkpoint.postgres import PostgresSaver

    try:
        with PostgresSaver.from_conn_string(_postgres_connection_string()) as saver:
            _setup_postgres_saver(saver)
    except Exception as exc:  # noqa: BLE001 - normalize driver/setup failures
        raise CheckpointStorageError("LangGraph checkpoint storage is unavailable") from exc


@contextmanager
def open_checkpointer() -> Iterator[Any]:
    """Yield a durable saver for production or a shared in-memory saver in tests."""

    if make_url(settings.DATABASE_URL).get_backend_name() != "postgresql":
        yield _memory_saver
        return

    from langgraph.checkpoint.postgres import PostgresSaver

    global _postgres_ready
    stack = ExitStack()
    try:
        saver = stack.enter_context(PostgresSaver.from_conn_string(_postgres_connection_string()))
        _setup_postgres_saver(saver)
    except Exception as exc:  # noqa: BLE001 - normalize driver/setup failures
        stack.close()
        raise CheckpointStorageError("LangGraph checkpoint storage is unavailable") from exc
    try:
        yield saver
    finally:
        stack.close()


def checkpoint_exists(task_id: str) -> bool:
    with open_checkpointer() as saver:
        return saver.get_tuple(checkpoint_config(task_id)) is not None


def delete_checkpoint_thread(task_id: str) -> None:
    with open_checkpointer() as saver:
        saver.delete_thread(task_id)
