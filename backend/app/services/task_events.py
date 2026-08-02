"""Cross-process task update notifications for the SSE API.

Workers publish tiny invalidation signals through Redis. The API owns database
serialization, so Redis never becomes a second source of truth for task state.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
from threading import Lock

import redis
import redis.asyncio as async_redis

from app.core.config import settings


logger = logging.getLogger(__name__)
_CHANNEL_PREFIX = "gameweave:task-events:"
_publisher: redis.Redis | None = None
_publisher_lock = Lock()
_publisher_retry_at = 0.0


class TaskEventsUnavailable(RuntimeError):
    """Redis task-event transport is unavailable."""


def task_event_channel(task_id: str) -> str:
    return f"{_CHANNEL_PREFIX}{task_id}"


def _publisher_client() -> redis.Redis:
    global _publisher
    if _publisher is None:
        _publisher = redis.Redis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=0.25,
            socket_timeout=0.25,
        )
    return _publisher


def publish_task_event(task_id: str, kind: str = "updated") -> None:
    """Best-effort invalidation signal; task commits must never depend on Redis."""

    if not settings.TASK_EVENTS_ENABLED or not task_id:
        return
    global _publisher, _publisher_retry_at
    now = time.monotonic()
    with _publisher_lock:
        if now < _publisher_retry_at:
            return
        try:
            _publisher_client().publish(
                task_event_channel(task_id),
                json.dumps({"task_id": task_id, "kind": kind}, separators=(",", ":")),
            )
        except redis.RedisError:
            _publisher = None
            _publisher_retry_at = now + 10.0
            logger.warning(
                "task event publish unavailable; SSE clients will use fallback refresh",
                extra={"generation_task_id": task_id},
                exc_info=True,
            )


async def subscribe_task_events(task_id: str) -> AsyncIterator[str | None]:
    """Yield Redis signals and ``None`` heartbeats for one task thread."""

    if not settings.TASK_EVENTS_ENABLED:
        raise TaskEventsUnavailable("task events are disabled")
    client = async_redis.Redis.from_url(
        settings.REDIS_URL,
        decode_responses=True,
        socket_connect_timeout=1.0,
        socket_timeout=None,
    )
    pubsub = client.pubsub()
    try:
        await pubsub.subscribe(task_event_channel(task_id))
        # Let the SSE handler reconcile its durable database cursor immediately
        # after the Redis subscription is active. This closes the otherwise
        # lossy window between taking the initial snapshot and subscribing.
        yield "subscribed"
        while True:
            message = await pubsub.get_message(
                ignore_subscribe_messages=True,
                timeout=settings.TASK_EVENTS_HEARTBEAT_SECONDS,
            )
            if not message:
                yield None
                continue
            # Coalesce bursts from log + step commits into one database refresh.
            await asyncio.sleep(0.1)
            while await pubsub.get_message(ignore_subscribe_messages=True, timeout=0):
                pass
            yield str(message["data"])
    except redis.RedisError as exc:
        raise TaskEventsUnavailable("task event transport is unavailable") from exc
    finally:
        try:
            await pubsub.unsubscribe(task_event_channel(task_id))
        except redis.RedisError:
            pass
        await pubsub.aclose()
        await client.aclose()
