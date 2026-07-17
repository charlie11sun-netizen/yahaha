from __future__ import annotations

import hashlib
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from openai import OpenAI
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError, OperationalError

from app.agents import detailed_trace
from app.core.config import settings
from app.core.telemetry import get_context
from app.db.session import SessionLocal
from app.models import AgentLog, AgentStep, GenerationTask, LLMCall
from app.services.task_events import publish_task_event

logger = logging.getLogger(__name__)

_DEFAULT_MODEL_PRICING = {
    "gpt-5.5": {"in": 1.25, "out": 10.0},
}
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
_STREAM_PROGRESS_INTERVAL_SECONDS = 1.0
_LEDGER_IDEMPOTENCY_CONSTRAINTS = {
    "uq_llm_calls_provider_response_id",
    "uq_llm_calls_run_request",
}


class LLMResponseError(RuntimeError):
    def __init__(self, message: str, *, code: str | None = None):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class LLMResult:
    text: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    model: str
    latency_ms: int
    cost_usd: Decimal | None = None
    partial: bool = False
    cached_tokens: int = 0
    cache_write_tokens: int = 0
    provider_response_id: str | None = None

    def __iter__(self):
        # Backward compatible with existing `raw, tokens = llm.chat(...)` calls.
        yield self.text
        yield self.total_tokens


def _client(*, timeout: int | None = None) -> OpenAI:
    return OpenAI(
        api_key=settings.OPENAI_API_KEY,
        base_url=settings.OPENAI_BASE_URL,
        timeout=timeout or settings.OPENAI_TIMEOUT,
        default_headers={"User-Agent": "GameWeave/1.0"},
        max_retries=0,
    )


def _status_code(exc: Exception) -> int | None:
    raw = getattr(exc, "status_code", None)
    if raw is None:
        response = getattr(exc, "response", None)
        raw = getattr(response, "status_code", None)
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def _retryable(exc: Exception) -> bool:
    status = _status_code(exc)
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


def _retry_delay(attempt: int) -> float:
    base = max(0.1, float(settings.OPENAI_RETRY_BACKOFF_SECONDS or 1.5))
    return min(10.0, base * (2 ** attempt))


def _close_sync_resource(resource: object | None, *, label: str) -> None:
    """Close SDK streams/clients without hiding the request's real outcome."""
    close = getattr(resource, "close", None)
    if not callable(close):
        return
    try:
        close()
    except Exception:  # noqa: BLE001 - cleanup must not replace the provider result
        logger.warning("failed to close OpenAI %s", label, exc_info=True)


def _stream_failure_payload(
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
        "status_code": _status_code(exc),
        "code": str(getattr(exc, "code", "") or "")[:120] or None,
        "cause_type": type(cause).__name__ if cause is not None else None,
        "cause_message": str(cause)[:500] if cause is not None else None,
    }


def _estimate_tokens(text_chars: int) -> int:
    return max(1, round(max(0, text_chars) / 4))


def _estimate_prompt_tokens(system: str, user: str) -> int:
    return _estimate_tokens(len(system or "") + len(user or ""))


def _complete_json_object(text: str) -> str | None:
    """Return canonical JSON only when an interrupted stream already contains a full object."""
    source = str(text or "").strip()
    start = source.find("{")
    if start < 0:
        return None
    try:
        value, end = json.JSONDecoder().raw_decode(source[start:])
    except json.JSONDecodeError:
        return None
    if not isinstance(value, dict) or not value:
        return None
    trailing = source[start + end :].strip()
    if trailing and trailing != "```":
        return None
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _pricing() -> dict:
    raw = (settings.MODEL_PRICING_JSON or "").strip()
    if not raw:
        return _DEFAULT_MODEL_PRICING
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else _DEFAULT_MODEL_PRICING
    except json.JSONDecodeError:
        return _DEFAULT_MODEL_PRICING


def _price_for(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    *,
    cached_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> Decimal | None:
    table = _pricing()
    price = table.get(model) or table.get(model.split(":")[0])
    if not isinstance(price, dict):
        return None
    try:
        input_per_million = Decimal(str(price["in"]))
        output_per_million = Decimal(str(price["out"]))
    except (KeyError, InvalidOperation):
        return None
    cached_tokens = min(max(0, int(cached_tokens or 0)), max(0, int(prompt_tokens or 0)))
    uncached_tokens = max(0, int(prompt_tokens or 0) - cached_tokens)
    cache_write_tokens = min(max(0, int(cache_write_tokens or 0)), uncached_tokens)
    regular_uncached_tokens = max(0, uncached_tokens - cache_write_tokens)
    # Providers do not all publish the same cache discount.  Apply one only when
    # deployment pricing explicitly supplies it; otherwise keep the old,
    # conservative input price instead of inventing a discount.
    try:
        cached_input_per_million = Decimal(str(price.get("cached_in", price["in"])))
    except (KeyError, InvalidOperation):
        cached_input_per_million = input_per_million
    try:
        cache_write_per_million = Decimal(str(price.get("cache_write_in", price["in"])))
    except (KeyError, InvalidOperation):
        cache_write_per_million = input_per_million
    cost = (
        Decimal(regular_uncached_tokens) * input_per_million
        + Decimal(cache_write_tokens) * cache_write_per_million
        + Decimal(cached_tokens) * cached_input_per_million
        + Decimal(completion_tokens) * output_per_million
    ) / Decimal(1_000_000)
    return cost.quantize(Decimal("0.000001"))


def _ledger_idempotency_constraint(exc: IntegrityError) -> str | None:
    """Identify only the two duplicate-response constraints as safe replay hits."""
    original = getattr(exc, "orig", None)
    diagnostic = getattr(original, "diag", None)
    constraint = getattr(diagnostic, "constraint_name", None)
    if constraint in _LEDGER_IDEMPOTENCY_CONSTRAINTS:
        return str(constraint)

    message = str(original or exc).lower()
    for name in _LEDGER_IDEMPOTENCY_CONSTRAINTS:
        if name.lower() in message:
            return name
    if "unique constraint failed: llm_calls.provider_response_id" in message:
        return "uq_llm_calls_provider_response_id"
    if (
        "unique constraint failed: llm_calls.run_id, llm_calls.request_index"
        in message
    ):
        return "uq_llm_calls_run_request"
    return None


def _persist_call(
    result: LLMResult,
    *,
    retried: bool = False,
    task_id: str | None = None,
    step_id: str | None = None,
    run_id: str | None = None,
    agent: str | None = None,
    workflow_name: str | None = None,
    provider_response_id: str | None = None,
    request_index: int | None = None,
    status: str = "completed",
    error_code: str | None = None,
) -> bool:
    ctx = get_context()
    task_id = task_id or ctx.get("task_id")
    step_id = step_id or ctx.get("step_id")
    if not task_id and not step_id:
        return False
    prompt_tokens = max(0, int(result.prompt_tokens or 0))
    completion_tokens = max(0, int(result.completion_tokens or 0))
    total_tokens = prompt_tokens + completion_tokens
    cached_tokens = min(max(0, int(result.cached_tokens or 0)), prompt_tokens)
    cache_write_tokens = min(
        max(0, int(result.cache_write_tokens or 0)),
        max(0, prompt_tokens - cached_tokens),
    )
    provider_response_id = provider_response_id or result.provider_response_id
    db = SessionLocal()
    try:
        if step_id and not task_id:
            step = db.get(AgentStep, step_id)
            task_id = step.task_id if step else None
        call = LLMCall(
            task_id=task_id,
            step_id=step_id,
            run_id=run_id,
            agent=agent or ctx.get("agent"),
            workflow_name=workflow_name,
            provider_response_id=provider_response_id,
            request_index=request_index,
            status=status,
            error_code=error_code,
            model=result.model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cached_tokens=cached_tokens,
            cache_write_tokens=cache_write_tokens,
            latency_ms=max(0, int(result.latency_ms or 0)),
            retried=retried,
            cost_usd=result.cost_usd,
        )
        db.add(call)
        # Flush before counters: a duplicate replay trips the unique ledger key
        # and therefore cannot increment task/step totals twice.
        db.flush()
        if step_id:
            db.query(AgentStep).filter(AgentStep.id == step_id).update(
                {AgentStep.tokens: func.coalesce(AgentStep.tokens, 0) + total_tokens},
                synchronize_session=False,
            )
        if task_id:
            values = {
                GenerationTask.tokens_used: func.coalesce(GenerationTask.tokens_used, 0)
                + total_tokens
            }
            if result.cost_usd is not None:
                values[GenerationTask.cost_usd] = (
                    func.coalesce(GenerationTask.cost_usd, Decimal("0")) + result.cost_usd
                )
            db.query(GenerationTask).filter(GenerationTask.id == task_id).update(
                values,
                synchronize_session=False,
            )
        db.commit()
        return True
    except IntegrityError as exc:
        db.rollback()
        if _ledger_idempotency_constraint(exc):
            # response.completed can be replayed after reconnect; the ledger key
            # is the idempotency boundary and the existing row is authoritative.
            return False
        logger.exception(
            "unexpected llm usage ledger integrity failure",
            extra={"generation_task_id": task_id, "step_id": step_id, "run_id": run_id},
        )
        return False
    except Exception:  # noqa: BLE001
        db.rollback()
        logger.exception(
            "llm usage ledger persistence failed",
            extra={"generation_task_id": task_id, "step_id": step_id, "run_id": run_id},
        )
        return False
    finally:
        db.close()


def _record_call(result: LLMResult, *, retried: bool = False) -> bool:
    return _persist_call(result, retried=retried)


def record_response_usage(
    *,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    cached_tokens: int = 0,
    cache_write_tokens: int = 0,
    latency_ms: int = 0,
    task_id: str | None = None,
    step_id: str | None = None,
    run_id: str,
    agent: str,
    workflow_name: str,
    provider_response_id: str | None,
    request_index: int,
    status: str = "completed",
    error_code: str | None = None,
) -> LLMResult:
    """Persist exactly one Agents SDK provider response.

    Unlike the legacy aggregate-at-run-end path, this survives MaxTurns and is
    safe when a streamed event is replayed.  ``llm_calls`` is the usage ledger;
    task and step counters are updated only if the ledger insert succeeds.
    """
    prompt_tokens = max(0, int(prompt_tokens or 0))
    completion_tokens = max(0, int(completion_tokens or 0))
    cached_tokens = min(max(0, int(cached_tokens or 0)), prompt_tokens)
    cache_write_tokens = min(
        max(0, int(cache_write_tokens or 0)),
        max(0, prompt_tokens - cached_tokens),
    )
    result = LLMResult(
        text="",
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
        model=model,
        latency_ms=max(0, int(latency_ms or 0)),
        cost_usd=_price_for(
            model,
            prompt_tokens,
            completion_tokens,
            cached_tokens=cached_tokens,
            cache_write_tokens=cache_write_tokens,
        ),
        cached_tokens=cached_tokens,
        cache_write_tokens=cache_write_tokens,
        provider_response_id=provider_response_id,
    )
    _persist_call(
        result,
        task_id=task_id,
        step_id=step_id,
        run_id=run_id,
        agent=agent,
        workflow_name=workflow_name,
        provider_response_id=provider_response_id,
        request_index=request_index,
        status=status,
        error_code=error_code,
    )
    return result


def prompt_cache_key(namespace: str, *, task_scoped: bool = True) -> str | None:
    """Return a stable routing key accepted by the Responses API.

    The provider combines this key with the exact prompt-prefix hash.  A task
    scope keeps author/retry runs isolated. Low-volume planning calls may opt
    into a shared versioned key so a new task's first node can reuse the same
    immutable planning constitution. Worker concurrency and task rate limits
    keep that shared key below the provider's recommended request rate.
    """
    prefix = str(settings.CODE_AGENT_PROMPT_CACHE_KEY_PREFIX or "").strip().rstrip(":")
    if not prefix:
        return None
    namespace = str(namespace or "default").strip() or "default"
    if not task_scoped:
        raw = f"{prefix}:{namespace}"
        if len(raw) <= 64:
            return raw
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
        namespace_budget = max(1, 64 - len(prefix[:32]) - len(digest) - 2)
        return f"{prefix[:32]}:{namespace[:namespace_budget]}:{digest}"
    task_scope = str(get_context().get("task_id") or "").replace("-", "")[:12]
    scope = task_scope or uuid.uuid4().hex[:12]
    raw = f"{prefix}:{namespace}:{scope}"
    if len(raw) <= 64:
        return raw
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
    prefix_part = prefix[:16]
    fixed = len(prefix_part) + len(scope) + len(digest) + 3
    namespace_budget = max(1, 64 - fixed)
    return f"{prefix_part}:{namespace[:namespace_budget]}:{scope}:{digest}"


def _supports_explicit_prompt_cache(model: str) -> bool:
    match = re.search(r"gpt-(\d+)(?:\.(\d+))?", str(model or "").lower())
    if not match:
        return False
    return (int(match.group(1)), int(match.group(2) or 0)) >= (5, 6)


def _explicit_cache_input(system: str, input_text: str, cache_prefix: str) -> list[dict]:
    if not cache_prefix:
        raise ValueError("cache_prefix must not be empty")
    if not system.startswith(cache_prefix):
        raise ValueError("system prompt must begin with the exact cache_prefix")
    node_instructions = system[len(cache_prefix) :].lstrip()
    if not node_instructions:
        raise ValueError("node-specific instructions must follow cache_prefix")
    return [
        {
            "type": "message",
            "role": "developer",
            "content": [
                {
                    "type": "input_text",
                    "text": cache_prefix,
                    "prompt_cache_breakpoint": {"mode": "explicit"},
                }
            ],
        },
        {
            "type": "message",
            "role": "developer",
            "content": [{"type": "input_text", "text": node_instructions}],
        },
        {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": input_text}],
        },
    ]


def _record_stream_progress(line: str, payload: dict | None = None) -> None:
    ctx = get_context()
    task_id = ctx.get("task_id")
    step_id = ctx.get("step_id")
    if not step_id:
        return
    # Serialize allocators on the parent step row.  COUNT was racy when model
    # progress and heartbeat/tool threads committed at the same time.
    last_error: Exception | None = None
    for attempt in range(3):
        db = SessionLocal()
        try:
            step = (
                db.query(AgentStep)
                .filter(AgentStep.id == step_id)
                .with_for_update()
                .one_or_none()
            )
            if step is None:
                return
            seq = (
                db.query(func.max(AgentLog.seq))
                .filter(AgentLog.step_id == step_id)
                .scalar()
            )
            db.add(
                AgentLog(
                    step_id=step_id,
                    seq=int(seq if seq is not None else -1) + 1,
                    line=line,
                    payload_json=json.dumps(payload, ensure_ascii=False) if payload else None,
                )
            )
            db.commit()
            publish_task_event(task_id or step.task_id, "log_appended")
            return
        except IntegrityError as exc:
            db.rollback()
            last_error = exc
        except OperationalError as exc:
            db.rollback()
            if "locked" not in str(exc).lower():
                logger.exception("model progress log write failed")
                return
            last_error = exc
        except Exception:  # noqa: BLE001
            db.rollback()
            logger.exception("model progress log write failed")
            return
        finally:
            db.close()
        if attempt < 2:
            time.sleep(0.01 * (attempt + 1))
    if last_error is not None:
        logger.warning("model progress log write exhausted retries: %s", last_error)


def record_usage(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    latency_ms: int,
    *,
    retried: bool = False,
    cached_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> LLMResult:
    """把外部执行的模型调用并入统一记账（LLMCall 行 + task.cost_usd）。

    Agents SDK 的工具循环（code_agent.py）自带 OpenAI client，不经过下面的
    chat()；此入口补齐相同的落库路径，保证 ops 查询与成本核算口径一致。
    """
    prompt_tokens = int(prompt_tokens or 0)
    completion_tokens = int(completion_tokens or 0)
    result = LLMResult(
        text="",
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
        model=model,
        latency_ms=int(latency_ms or 0),
        cost_usd=_price_for(
            model,
            prompt_tokens,
            completion_tokens,
            cached_tokens=cached_tokens,
            cache_write_tokens=cache_write_tokens,
        ),
        cached_tokens=int(cached_tokens or 0),
        cache_write_tokens=int(cache_write_tokens or 0),
    )
    _record_call(result, retried=retried)
    return result


def _extract_response_text(response: object | None) -> str:
    chunks: list[str] = []
    for item in getattr(response, "output", []) or []:
        for part in getattr(item, "content", []) or []:
            text = getattr(part, "text", None)
            if text:
                chunks.append(str(text))
    return "".join(chunks)


def _event_error(event: object) -> LLMResponseError:
    error = getattr(event, "error", None)
    if error is None:
        response = getattr(event, "response", None)
        error = getattr(response, "error", None)
    if error is None and (
        getattr(event, "code", None) is not None
        or getattr(event, "message", None) is not None
    ):
        # The Responses SDK's top-level `error` stream event is itself a
        # ResponseErrorEvent (code/message live directly on the event).  Losing
        # that code turns transient internal_server_error events into permanent
        # failures and skips the configured retry loop.
        error = event
    if error is None:
        return LLMResponseError(str(event))
    message = getattr(error, "message", None) or getattr(error, "code", None) or str(error)
    code = getattr(error, "code", None)
    return LLMResponseError(str(message), code=str(code) if code else None)


def _partial_stream_result(
    *,
    text: str,
    requested_model: str,
    system: str,
    input_text: str,
    start: float,
    retried: bool,
) -> LLMResult:
    latency_ms = int((time.perf_counter() - start) * 1000)
    prompt_tokens = _estimate_prompt_tokens(system, input_text)
    completion_tokens = _estimate_tokens(len(text))
    result = LLMResult(
        text=text.strip(),
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
        model=requested_model,
        latency_ms=latency_ms,
        cost_usd=_price_for(requested_model, prompt_tokens, completion_tokens),
        partial=True,
    )
    _record_stream_progress(f"stream_tokens={completion_tokens}")
    _record_call(result, retried=retried)
    return result


def chat(
    system: str,
    user: str,
    temperature: float | None = None,
    max_tokens: int | None = None,
    *,
    model: str | None = None,
    timeout: int | None = None,
    response_format: dict | None = None,
    allow_partial: bool = False,
    recover_partial_json: bool = False,
    cache_namespace: str | None = None,
    cache_prefix: str | None = None,
    cache_task_scoped: bool = True,
    images_b64: list[str] | None = None,
) -> LLMResult:
    requested_model = model or settings.MODEL_NAME
    input_text = user
    if response_format is not None and response_format.get("type") == "json_object":
        input_text = (
            f"{user}\n\n"
            "Return only a valid JSON object. Do not include markdown fences or extra text."
        )
    if images_b64 and cache_prefix is not None:
        raise ValueError("images_b64 cannot be combined with explicit cache_prefix input")
    model_input: object = input_text
    if images_b64:
        model_input = [
            {
                "type": "message",
                "role": "user",
                "content": [
                    {"type": "input_text", "text": input_text},
                    *(
                        {
                            "type": "input_image",
                            "image_url": f"data:image/png;base64,{image}",
                            "detail": "low",
                        }
                        for image in images_b64
                    ),
                ],
            }
        ]
    kwargs: dict = {
        "model": requested_model,
        "instructions": system,
        "input": model_input,
        "stream": True,
        "store": False,
    }
    cache_key = (
        prompt_cache_key(cache_namespace, task_scoped=cache_task_scoped)
        if cache_namespace
        else None
    )
    if cache_key:
        kwargs["prompt_cache_key"] = cache_key
    if cache_prefix is not None:
        if not cache_namespace:
            raise ValueError("cache_namespace is required when cache_prefix is provided")
        if not system.startswith(cache_prefix):
            raise ValueError("system prompt must begin with the exact cache_prefix")
        if (
            cache_key
            and settings.OPENAI_EXPLICIT_PROMPT_CACHE_ENABLED
            and _supports_explicit_prompt_cache(requested_model)
        ):
            kwargs.pop("instructions", None)
            kwargs["input"] = _explicit_cache_input(system, input_text, cache_prefix)
            kwargs["prompt_cache_options"] = {"mode": "explicit", "ttl": "30m"}
    if temperature is not None:
        kwargs["temperature"] = temperature
    if max_tokens is not None:
        kwargs["max_output_tokens"] = max_tokens
    if response_format is not None and response_format.get("type") != "json_object":
        kwargs["text"] = {"format": response_format}

    context = get_context()
    trace_recorder = detailed_trace.create_recorder(
        source="responses_api",
        agent=context.get("agent") or "GameCodeAgent",
        model=requested_model,
        require_code_context=True,
    )
    if trace_recorder:
        trace_recorder.record(
            "run_start",
            {
                "system_prompt": system,
                "user_input": user,
                "request": kwargs,
                "response_format": response_format,
                "allow_partial": allow_partial,
                "recover_partial_json": recover_partial_json,
                "timeout": timeout,
            },
        )

    max_retries = max(0, int(settings.OPENAI_MAX_RETRIES or 0))
    partial_min_chars = max(0, int(settings.OPENAI_PARTIAL_STREAM_MIN_CHARS or 0))
    retried = False
    best_partial_text = ""
    best_partial_started_at = time.perf_counter()
    for attempt in range(max_retries + 1):
        start = time.perf_counter()
        text_parts: list[str] = []
        done_text = ""
        completed_response = None
        streamed_chars = 0
        client = None
        stream = None
        try:
            if trace_recorder:
                trace_recorder.record(
                    "llm_input",
                    {"attempt": attempt + 1, "request": kwargs},
                )
            _record_stream_progress("stream_tokens=0")
            client = _client(timeout=timeout)
            stream = client.responses.create(**kwargs)
            last_progress_at = start
            for event in stream:
                event_type = getattr(event, "type", "")
                if event_type == "response.output_text.delta":
                    delta = str(getattr(event, "delta", "") or "")
                    text_parts.append(delta)
                    streamed_chars += len(delta)
                    now = time.perf_counter()
                    if now - last_progress_at >= _STREAM_PROGRESS_INTERVAL_SECONDS:
                        _record_stream_progress(f"stream_tokens={_estimate_tokens(streamed_chars)}")
                        last_progress_at = now
                elif event_type == "response.output_text.done":
                    done_text = str(getattr(event, "text", "") or "")
                elif event_type == "response.completed":
                    completed_response = getattr(event, "response", None)
                elif event_type in {"response.failed", "response.incomplete", "error"}:
                    raise _event_error(event)
            if completed_response is None:
                partial_text = ("".join(text_parts) or done_text).strip()
                if allow_partial and len(partial_text) >= partial_min_chars:
                    partial_result = _partial_stream_result(
                        text=partial_text,
                        requested_model=requested_model,
                        system=system,
                        input_text=input_text,
                        start=start,
                        retried=retried,
                    )
                    if trace_recorder:
                        trace_recorder.record(
                            "llm_output",
                            {
                                "attempt": attempt + 1,
                                "partial": True,
                                "text": partial_result.text,
                                "usage": partial_result,
                                "reason": "stream_ended_before_completed",
                            },
                        )
                        trace_recorder.record(
                            "run_end",
                            {"status": "partial", "result": partial_result},
                        )
                    return partial_result
                raise RuntimeError("Responses stream ended before response.completed")
            break
        except Exception as exc:  # noqa: BLE001
            partial_text = ("".join(text_parts) or done_text).strip()
            if len(partial_text) > len(best_partial_text):
                best_partial_text = partial_text
                best_partial_started_at = start
            if allow_partial and len(partial_text) >= partial_min_chars:
                partial_result = _partial_stream_result(
                    text=partial_text,
                    requested_model=requested_model,
                    system=system,
                    input_text=input_text,
                    start=start,
                    retried=retried,
                )
                if trace_recorder:
                    trace_recorder.record(
                        "llm_error",
                        {
                            "attempt": attempt + 1,
                            "partial_text": partial_text,
                            "will_retry": False,
                            **detailed_trace.exception_payload(exc),
                        },
                    )
                    trace_recorder.record(
                        "llm_output",
                        {
                            "attempt": attempt + 1,
                            "partial": True,
                            "text": partial_result.text,
                            "usage": partial_result,
                            "reason": "stream_error_with_usable_partial",
                        },
                    )
                    trace_recorder.record(
                        "run_end",
                        {"status": "partial", "result": partial_result},
                    )
                return partial_result
            retryable = _retryable(exc)
            will_retry = attempt < max_retries and retryable
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            failure_payload = _stream_failure_payload(
                exc,
                attempt=attempt + 1,
                elapsed_ms=elapsed_ms,
                partial_chars=len(partial_text),
                will_retry=will_retry,
            )
            _record_stream_progress(
                (
                    f"stream attempt {attempt + 1} failed after {elapsed_ms}ms: "
                    f"{type(exc).__name__}; "
                    f"{'retrying' if will_retry else 'not retrying'}"
                ),
                payload=failure_payload,
            )
            if trace_recorder:
                trace_recorder.record(
                    "llm_error",
                    {
                        "attempt": attempt + 1,
                        "partial_text": partial_text,
                        "will_retry": will_retry,
                        **detailed_trace.exception_payload(exc),
                    },
                )
            if not will_retry:
                recovered_json = (
                    _complete_json_object(best_partial_text)
                    if recover_partial_json
                    and retryable
                    else None
                )
                if recovered_json is not None:
                    partial_result = _partial_stream_result(
                        text=recovered_json,
                        requested_model=requested_model,
                        system=system,
                        input_text=input_text,
                        start=best_partial_started_at,
                        retried=retried,
                    )
                    if trace_recorder:
                        trace_recorder.record(
                            "llm_output",
                            {
                                "attempt": attempt + 1,
                                "partial": True,
                                "text": partial_result.text,
                                "usage": partial_result,
                                "reason": "complete_json_recovered_after_stream_retries",
                            },
                        )
                        trace_recorder.record(
                            "run_end",
                            {
                                "status": "partial",
                                "attempts": attempt + 1,
                                "retried": retried,
                                "result": partial_result,
                            },
                        )
                    return partial_result
                if trace_recorder:
                    trace_recorder.record(
                        "run_end",
                        {"status": "failed", "attempts": attempt + 1},
                    )
                raise
            retried = True
            time.sleep(_retry_delay(attempt))
        finally:
            _close_sync_resource(stream, label="response stream")
            _close_sync_resource(client, label="client")
    latency_ms = int((time.perf_counter() - start) * 1000)
    text = ("".join(text_parts) or done_text or _extract_response_text(completed_response)).strip()
    usage = getattr(completed_response, "usage", None)
    prompt_tokens = int(
        getattr(usage, "input_tokens", 0) or getattr(usage, "prompt_tokens", 0) or 0
    ) if usage else 0
    completion_tokens = int(
        getattr(usage, "output_tokens", 0) or getattr(usage, "completion_tokens", 0) or 0
    ) if usage else 0
    total_tokens = int(getattr(usage, "total_tokens", 0) or 0) if usage else 0
    if total_tokens <= 0:
        total_tokens = prompt_tokens + completion_tokens
    usage_details = getattr(usage, "input_tokens_details", None) if usage else None
    cached_tokens = int(getattr(usage_details, "cached_tokens", 0) or 0)
    cache_write_tokens = int(getattr(usage_details, "cache_write_tokens", 0) or 0)
    if latency_ms >= int(_STREAM_PROGRESS_INTERVAL_SECONDS * 1000):
        _record_stream_progress(f"stream_tokens={completion_tokens or _estimate_tokens(len(text))}")
    actual_model = str(getattr(completed_response, "model", None) or requested_model)
    if prompt_tokens:
        # 0% 也要落一行：一次性调用的命中率此前无人观测，"零"与"没测"必须可区分。
        cache_pct = cached_tokens * 100 // prompt_tokens
        cache_line = f"prompt cache: {cached_tokens}/{prompt_tokens} read ({cache_pct}%)"
        if cache_write_tokens:
            cache_line += f", {cache_write_tokens} written"
        _record_stream_progress(
            cache_line,
            payload={
                "type": "usage",
                "input_tokens": prompt_tokens,
                "output_tokens": completion_tokens,
                "total_tokens": total_tokens,
                "cached_tokens": cached_tokens,
                "cache_write_tokens": cache_write_tokens,
                "requests": 1,
                "cache_percent": cache_pct,
                "prompt_cache_key": cache_key,
                "prompt_cache_namespace": cache_namespace,
                "prompt_cache_mode": (
                    "explicit" if "prompt_cache_options" in kwargs else "implicit"
                ) if cache_key else None,
            },
        )
    result = LLMResult(
        text=text,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        model=actual_model,
        latency_ms=latency_ms,
        cost_usd=_price_for(
            actual_model,
            prompt_tokens,
            completion_tokens,
            cached_tokens=cached_tokens,
            cache_write_tokens=cache_write_tokens,
        ),
        cached_tokens=cached_tokens,
        cache_write_tokens=cache_write_tokens,
        provider_response_id=str(getattr(completed_response, "id", "") or "") or None,
    )
    if trace_recorder:
        trace_recorder.record(
            "llm_output",
            {
                "attempt": attempt + 1,
                "partial": False,
                "text": text,
                "response": completed_response,
                "usage": result,
            },
            model=actual_model,
        )
    _record_call(result, retried=retried)
    if trace_recorder:
        trace_recorder.record(
            "run_end",
            {
                "status": "completed",
                "attempts": attempt + 1,
                "retried": retried,
                "result": result,
            },
            model=actual_model,
        )
    return result
