"""Fail-open integration with a self-hosted Opik instance.

Opik is deliberately optional at import time. The existing PostgreSQL trace
tables remain the audit source, while this module adds a best-effort export
for Agent/LLM observability when OPIK_ENABLED and OPIK_URL_OVERRIDE are set.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
from contextlib import contextmanager
from typing import Any, Iterator
from urllib.parse import urlparse

from app.core.config import settings
from app.agents.decision_trace import DECISION_TRACE_SCHEMA_VERSION

logger = logging.getLogger(__name__)

_CONFIG_LOCK = threading.Lock()
_AGENTS_CONFIGURED = False
GENERATION_TRACE_SCHEMA_VERSION = "gameweave.opik.generation/1.0"


def enabled() -> bool:
    return bool(settings.OPIK_ENABLED and settings.OPIK_URL_OVERRIDE.strip())


def _apply_environment() -> bool:
    if not enabled():
        return False
    url_override = settings.OPIK_URL_OVERRIDE.strip()
    os.environ["OPIK_URL_OVERRIDE"] = url_override
    os.environ["OPIK_PROJECT_NAME"] = settings.OPIK_PROJECT_NAME.strip() or "gameweave-agent"
    os.environ["OPIK_WORKSPACE"] = settings.OPIK_WORKSPACE.strip() or "default"
    if settings.OPIK_ENVIRONMENT.strip():
        os.environ["OPIK_ENVIRONMENT"] = settings.OPIK_ENVIRONMENT.strip()
    # Self-hosted Opik does not require a Comet API key.
    os.environ.pop("OPIK_API_KEY", None)
    # The desktop environment may expose an HTTP proxy globally.  A local
    # self-hosted Opik endpoint must bypass it; otherwise httpx can return a
    # proxy-generated 503 even though the Opik service is healthy.
    host = urlparse(url_override).hostname
    if host:
        bypass_hosts = {"localhost", "127.0.0.1", host}
        existing = os.environ.get("NO_PROXY", os.environ.get("no_proxy", ""))
        bypass_hosts.update(part.strip() for part in existing.split(",") if part.strip())
        no_proxy = ",".join(sorted(bypass_hosts))
        os.environ["NO_PROXY"] = no_proxy
        os.environ["no_proxy"] = no_proxy
    return True


@contextmanager
def _fail_open_context(manager_factory, *, label: str) -> Iterator[Any | None]:
    """Enter an Opik context without letting telemetry break generation."""
    try:
        manager = manager_factory()
        value = manager.__enter__()
    except Exception as exc:  # noqa: BLE001 - observability must fail open
        logger.warning("Opik %s unavailable: %s", label, exc)
        yield None
        return

    try:
        yield value
    except BaseException:  # preserve the generation exception after recording it
        exc_info = sys.exc_info()
        try:
            manager.__exit__(*exc_info)
        except Exception as telemetry_exc:  # noqa: BLE001
            logger.warning("Opik %s error finalization failed: %s", label, telemetry_exc)
        raise
    else:
        try:
            manager.__exit__(None, None, None)
        except Exception as exc:  # noqa: BLE001 - observability must fail open
            logger.warning("Opik %s finalization failed: %s", label, exc)


@contextmanager
def generation_trace(
    *,
    task_id: str,
    dispatch_generation: int | None = None,
) -> Iterator[Any | None]:
    """Create the task-level root trace used to group one generation flow."""
    if not _apply_environment():
        yield None
        return

    try:
        from opik import start_as_current_trace
    except Exception as exc:  # noqa: BLE001 - observability must fail open
        logger.warning("Opik generation root trace unavailable: %s", exc)
        yield None
        return

    metadata = {
            "schema_version": GENERATION_TRACE_SCHEMA_VERSION,
            "decision_schema_version": DECISION_TRACE_SCHEMA_VERSION,
        "task_id": task_id,
        "dispatch_generation": dispatch_generation,
        "environment": settings.OPIK_ENVIRONMENT.strip() or None,
    }
    tags = ["gameweave", "game-generation"]
    with _fail_open_context(
        lambda: start_as_current_trace(
            name="game-generation",
            input={"task_id": task_id},
            metadata=metadata,
            tags=tags,
            project_name=settings.OPIK_PROJECT_NAME.strip() or "gameweave-agent",
            thread_id=f"task:{task_id}",
        ),
        label="generation root trace",
    ) as trace:
        yield trace


@contextmanager
def generation_span(
    *,
    node_name: str,
    task_id: str,
    step_id: str | None,
    agent: str,
    display_name: str,
) -> Iterator[Any | None]:
    """Create a stage span below the active generation root trace."""
    if not _apply_environment():
        yield None
        return

    try:
        from opik import start_as_current_span
    except Exception as exc:  # noqa: BLE001 - observability must fail open
        logger.warning("Opik stage span unavailable: %s", exc)
        yield None
        return

    with _fail_open_context(
        lambda: start_as_current_span(
            name=f"stage.{node_name}",
            input={"task_id": task_id, "step_id": step_id},
            metadata={
                "schema_version": GENERATION_TRACE_SCHEMA_VERSION,
                "decision_schema_version": DECISION_TRACE_SCHEMA_VERSION,
                "task_id": task_id,
                "step_id": step_id,
                "node_name": node_name,
                "agent": agent,
                "display_name": display_name,
            },
            tags=["gameweave-stage", f"agent:{agent}"],
        ),
        label=f"stage span {node_name}",
    ) as span:
        if span is not None:
            try:
                from opik import opik_context

                # Opik 2.1.x applies metadata/tags supplied to the context
                # manager at span finalization; update the active span now so
                # the searchable task identifiers are retained even when a
                # later update only adds terminal status fields.
                opik_context.update_current_span(
                    metadata={
                        "schema_version": GENERATION_TRACE_SCHEMA_VERSION,
                        "decision_schema_version": DECISION_TRACE_SCHEMA_VERSION,
                        "task_id": task_id,
                        "step_id": step_id,
                        "node_name": node_name,
                        "agent": agent,
                        "display_name": display_name,
                    },
                    tags=["gameweave-stage", f"agent:{agent}"],
                )
            except Exception as exc:  # noqa: BLE001 - observability must fail open
                logger.warning("Opik stage span metadata update failed: %s", exc)
        yield span


def update_generation_trace(
    *,
    name: str | None = None,
    input: dict[str, Any] | None = None,
    output: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    tags: list[str] | None = None,
    thread_id: str | None = None,
) -> None:
    """Merge searchable task/game fields into the active root trace."""
    if not enabled():
        return
    try:
        from opik import opik_context

        opik_context.update_current_trace(
            name=name,
            input=input,
            output=output,
            metadata=metadata,
            tags=tags,
            thread_id=thread_id,
        )
    except Exception as exc:  # noqa: BLE001 - observability must fail open
        logger.warning("Opik generation trace update failed: %s", exc)


def update_generation_span(
    *,
    output: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    tags: list[str] | None = None,
) -> None:
    """Merge terminal stage data into the active stage span."""
    if not enabled():
        return
    try:
        from opik import opik_context

        opik_context.update_current_span(output=output, metadata=metadata, tags=tags)
    except Exception as exc:  # noqa: BLE001 - observability must fail open
        logger.warning("Opik generation span update failed: %s", exc)


def configure_agents_tracing() -> bool:
    """Register the OpenAI Agents processor once per worker process."""
    global _AGENTS_CONFIGURED
    if not _apply_environment():
        return False
    with _CONFIG_LOCK:
        if _AGENTS_CONFIGURED:
            return True
        try:
            from agents import set_trace_processors
            from opik.integrations.openai.agents import OpikTracingProcessor

            set_trace_processors(processors=[OpikTracingProcessor()])
        except Exception as exc:  # noqa: BLE001 - observability must fail open
            logger.warning("Opik Agents tracing unavailable: %s", exc)
            return False
        _AGENTS_CONFIGURED = True
        logger.info(
            "Opik Agents tracing enabled project=%s url=%s",
            settings.OPIK_PROJECT_NAME,
            settings.OPIK_URL_OVERRIDE,
        )
        return True


def wrap_openai_client(client: Any) -> Any:
    """Wrap an OpenAI client so Responses API calls are sent to Opik."""
    if not _apply_environment():
        return client
    try:
        from opik.integrations.openai import track_openai

        return track_openai(
            client,
            project_name=settings.OPIK_PROJECT_NAME.strip() or "gameweave-agent",
        )
    except Exception as exc:  # noqa: BLE001 - observability must fail open
        logger.warning("Opik OpenAI tracing unavailable: %s", exc)
        return client


def flush() -> None:
    """Flush the SDK batch queue at a Celery task/run boundary."""
    if not enabled():
        return
    try:
        from opik import flush_tracker

        flush_tracker()
    except Exception as exc:  # noqa: BLE001 - observability must fail open
        logger.warning("Opik trace flush failed: %s", exc)


__all__ = [
    "GENERATION_TRACE_SCHEMA_VERSION",
    "configure_agents_tracing",
    "enabled",
    "flush",
    "generation_span",
    "generation_trace",
    "update_generation_span",
    "update_generation_trace",
    "wrap_openai_client",
]
