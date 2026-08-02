from __future__ import annotations

"""OpenAI transport, retry classification, and Responses API event helpers."""

import logging

from openai import OpenAI

from app.observability import opik_integration
from app.core.config import settings

logger = logging.getLogger(__name__)

STREAM_PROGRESS_INTERVAL_SECONDS = 1.0

_TRANSIENT_STATUS_CODES = {408, 409, 429, 500, 502, 503, 504, 520, 522, 524}
_TRANSIENT_ERROR_CODES = {
    "internal_server_error",
    "rate_limit_exceeded",
    "server_error",
    "vector_store_timeout",
}
_TRANSIENT_ERROR_MESSAGES = (
    "retry your request",
    "temporarily unavailable",
    "temporary error",
    "internal server error",
    "server error",
    "service unavailable",
    "rate limit",
    "overloaded",
)


class LLMResponseError(RuntimeError):
    def __init__(self, message: str, *, code: str | None = None):
        super().__init__(message)
        self.code = code


def client(*, timeout: int | None = None) -> OpenAI:
    raw_client = OpenAI(
        api_key=settings.OPENAI_API_KEY,
        base_url=settings.OPENAI_BASE_URL,
        timeout=timeout or settings.OPENAI_TIMEOUT,
        default_headers={"User-Agent": "GameWeave/1.0"},
        max_retries=0,
    )
    return opik_integration.wrap_openai_client(raw_client)


def status_code(exc: Exception) -> int | None:
    raw = getattr(exc, "status_code", None)
    if raw is None:
        response = getattr(exc, "response", None)
        raw = getattr(response, "status_code", None)
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def retryable(exc: Exception) -> bool:
    status = status_code(exc)
    if status in _TRANSIENT_STATUS_CODES:
        return True
    code = str(getattr(exc, "code", "") or "").lower()
    if code in _TRANSIENT_ERROR_CODES:
        return True
    message = str(exc).lower()
    return any(
        marker in message
        for marker in ("timeout", "timed out", "connection", *_TRANSIENT_ERROR_MESSAGES)
    )


def retry_delay(attempt: int) -> float:
    base = max(0.1, float(settings.OPENAI_RETRY_BACKOFF_SECONDS or 1.5))
    return min(10.0, base * (2**attempt))


def close_sync_resource(resource: object | None, *, label: str) -> None:
    """Close SDK streams/clients without hiding the request's real outcome."""
    close = getattr(resource, "close", None)
    if not callable(close):
        return
    try:
        close()
    except Exception:  # noqa: BLE001 - cleanup must not replace the provider result
        logger.warning("failed to close OpenAI %s", label, exc_info=True)


def stream_failure_payload(
    exc: BaseException,
    *,
    attempt: int,
    elapsed_ms: int,
    partial_chars: int,
    will_retry: bool,
) -> dict:
    cause = exc.__cause__ or exc.__context__
    return {
        "type": "llm_stream_error",
        "attempt": attempt,
        "elapsed_ms": max(0, int(elapsed_ms)),
        "partial_chars": max(0, int(partial_chars)),
        "will_retry": bool(will_retry),
        "exception_type": type(exc).__name__,
        "message": str(exc)[:500],
        "status_code": status_code(exc),
        "code": str(getattr(exc, "code", "") or "")[:120] or None,
        "cause_type": type(cause).__name__ if cause is not None else None,
        "cause_message": str(cause)[:500] if cause is not None else None,
    }


def extract_response_text(response: object | None) -> str:
    chunks: list[str] = []
    for item in getattr(response, "output", []) or []:
        for part in getattr(item, "content", []) or []:
            text = getattr(part, "text", None)
            if text:
                chunks.append(str(text))
    return "".join(chunks)


def event_error(event: object) -> LLMResponseError:
    error = getattr(event, "error", None)
    if error is None:
        response = getattr(event, "response", None)
        error = getattr(response, "error", None)
    if error is None and (
        getattr(event, "code", None) is not None
        or getattr(event, "message", None) is not None
    ):
        # Top-level Responses API error events carry code/message directly.
        error = event
    if error is None:
        return LLMResponseError(str(event))
    message = getattr(error, "message", None) or getattr(error, "code", None) or str(error)
    code = getattr(error, "code", None)
    return LLMResponseError(str(message), code=str(code) if code else None)
