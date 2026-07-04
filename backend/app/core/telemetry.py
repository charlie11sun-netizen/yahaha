from __future__ import annotations

import logging
import sys
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from app.core.config import settings

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
_user_id: ContextVar[str | None] = ContextVar("user_id", default=None)
_task_id: ContextVar[str | None] = ContextVar("task_id", default=None)
_step_id: ContextVar[str | None] = ContextVar("step_id", default=None)
_agent: ContextVar[str | None] = ContextVar("agent", default=None)
_node_name: ContextVar[str | None] = ContextVar("node_name", default=None)

_LOGGING_CONFIGURED = False
_SENTRY_CONFIGURED = False
_OTEL_CONFIGURED = False
_SENSITIVE_EVENT_KEYS = {
    "authorization",
    "cookie",
    "email",
    "idea",
    "password",
    "password_hash",
    "prompt",
    "set-cookie",
    "x-gate-token",
}


def _maybe_structlog():
    try:
        import structlog  # type: ignore

        return structlog
    except Exception:  # noqa: BLE001
        return None


def _contextvars() -> dict[str, str]:
    values = {
        "request_id": _request_id.get(),
        "user_id": _user_id.get(),
        "task_id": _task_id.get(),
        "step_id": _step_id.get(),
        "agent": _agent.get(),
        "node_name": _node_name.get(),
    }
    return {key: value for key, value in values.items() if value}


def get_context() -> dict[str, str]:
    return _contextvars()


def current_request_id() -> str | None:
    return _request_id.get()


def bind_context(**values: str | None) -> None:
    mapping = {
        "request_id": _request_id,
        "user_id": _user_id,
        "task_id": _task_id,
        "step_id": _step_id,
        "agent": _agent,
        "node_name": _node_name,
    }
    bound: dict[str, str] = {}
    for key, value in values.items():
        var = mapping.get(key)
        if not var:
            continue
        var.set(value)
        if value is not None:
            bound[key] = value
    structlog = _maybe_structlog()
    if structlog and bound:
        try:
            structlog.contextvars.bind_contextvars(**bound)
        except Exception:  # noqa: BLE001
            pass


def clear_context() -> None:
    bind_context(
        request_id=None,
        user_id=None,
        task_id=None,
        step_id=None,
        agent=None,
        node_name=None,
    )
    structlog = _maybe_structlog()
    if structlog:
        try:
            structlog.contextvars.clear_contextvars()
        except Exception:  # noqa: BLE001
            pass


def configure_logging() -> None:
    global _LOGGING_CONFIGURED
    if _LOGGING_CONFIGURED:
        return
    _LOGGING_CONFIGURED = True

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stdout)

    structlog = _maybe_structlog()
    if structlog:
        timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)
        renderer = (
            structlog.processors.JSONRenderer()
            if (settings.LOG_FORMAT or "").lower() == "json"
            else structlog.dev.ConsoleRenderer()
        )
        foreign_pre_chain = [
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            timestamper,
        ]
        handler.setFormatter(
            structlog.stdlib.ProcessorFormatter(
                processor=renderer,
                foreign_pre_chain=foreign_pre_chain,
            )
        )
        structlog.configure(
            processors=[
                structlog.contextvars.merge_contextvars,
                structlog.stdlib.add_logger_name,
                structlog.stdlib.add_log_level,
                timestamper,
                structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
            ],
            logger_factory=structlog.stdlib.LoggerFactory(),
            wrapper_class=structlog.stdlib.BoundLogger,
            cache_logger_on_first_use=True,
        )
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root.addHandler(handler)


def get_logger(name: str):
    structlog = _maybe_structlog()
    if structlog:
        return structlog.get_logger(name)
    return logging.getLogger(name)


def log_info(logger, event: str, **fields: Any) -> None:
    try:
        logger.info(event, **fields)
    except TypeError:
        rendered = " ".join(f"{key}={value}" for key, value in fields.items())
        logger.info("%s %s", event, rendered)


def _scrub_value(value):
    if isinstance(value, dict):
        for key in list(value):
            if key.lower() in _SENSITIVE_EVENT_KEYS:
                value[key] = "[Filtered]"
            else:
                value[key] = _scrub_value(value[key])
    elif isinstance(value, list):
        for index, item in enumerate(value):
            value[index] = _scrub_value(item)
    return value


def _scrub_event(event: dict) -> dict | None:
    tags = event.setdefault("tags", {})
    tags.update(_contextvars())
    request = event.get("request") or {}
    if isinstance(request, dict):
        request.pop("data", None)
        request.pop("cookies", None)
        headers = request.get("headers")
        if isinstance(headers, dict):
            for key in list(headers):
                if key.lower() in {"authorization", "cookie", "set-cookie", "x-gate-token"}:
                    headers[key] = "[Filtered]"
    return _scrub_value(event)


def init_sentry(service_name: str) -> None:
    global _SENTRY_CONFIGURED
    if _SENTRY_CONFIGURED or not settings.SENTRY_DSN.strip():
        return
    _SENTRY_CONFIGURED = True
    try:
        import sentry_sdk  # type: ignore
        from sentry_sdk.integrations.celery import CeleryIntegration  # type: ignore
        from sentry_sdk.integrations.fastapi import FastApiIntegration  # type: ignore
    except Exception as exc:  # noqa: BLE001
        logging.getLogger(__name__).warning("Sentry disabled; import failed: %s", exc)
        return
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=settings.SENTRY_ENVIRONMENT,
        release=service_name,
        send_default_pii=False,
        before_send=_scrub_event,
        traces_sample_rate=0.0,
        integrations=[FastApiIntegration(), CeleryIntegration()],
    )


def init_otel(*, service_name: str, fastapi_app=None, sqlalchemy_engine=None) -> None:
    global _OTEL_CONFIGURED
    endpoint = settings.OTEL_EXPORTER_OTLP_ENDPOINT.strip()
    if _OTEL_CONFIGURED or not endpoint:
        return
    _OTEL_CONFIGURED = True
    try:
        from opentelemetry import trace  # type: ignore
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter  # type: ignore
        from opentelemetry.instrumentation.celery import CeleryInstrumentor  # type: ignore
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor  # type: ignore
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor  # type: ignore
        from opentelemetry.instrumentation.redis import RedisInstrumentor  # type: ignore
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor  # type: ignore
        from opentelemetry.sdk.resources import Resource  # type: ignore
        from opentelemetry.sdk.trace import TracerProvider  # type: ignore
        from opentelemetry.sdk.trace.export import BatchSpanProcessor  # type: ignore
        from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased  # type: ignore
    except Exception as exc:  # noqa: BLE001
        logging.getLogger(__name__).warning("OpenTelemetry disabled; import failed: %s", exc)
        return

    sampler = ParentBased(TraceIdRatioBased(float(settings.OTEL_TRACES_SAMPLE_RATE or 0)))
    provider = TracerProvider(
        resource=Resource.create({"service.name": service_name}),
        sampler=sampler,
    )
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(provider)
    if sqlalchemy_engine is not None:
        SQLAlchemyInstrumentor().instrument(engine=sqlalchemy_engine)
    RedisInstrumentor().instrument()
    CeleryInstrumentor().instrument()
    HTTPXClientInstrumentor().instrument()
    if fastapi_app is not None:
        FastAPIInstrumentor.instrument_app(fastapi_app)


class _NoopSpan:
    def set_attribute(self, *_args, **_kwargs) -> None:
        return None

    def record_exception(self, *_args, **_kwargs) -> None:
        return None


@contextmanager
def agent_span(name: str, attributes: dict[str, Any] | None = None):
    if not settings.OTEL_EXPORTER_OTLP_ENDPOINT.strip():
        yield _NoopSpan()
        return
    try:
        from opentelemetry import trace  # type: ignore
    except Exception:  # noqa: BLE001
        yield _NoopSpan()
        return

    tracer = trace.get_tracer("gameweave.agents")
    with tracer.start_as_current_span(name) as span:
        for key, value in (attributes or {}).items():
            if value is not None:
                span.set_attribute(key, value)
        yield span
