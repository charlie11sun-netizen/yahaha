from __future__ import annotations

import json
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from openai import OpenAI
from sqlalchemy import func

from app.agents import detailed_trace
from app.core.config import settings
from app.core.telemetry import get_context
from app.db.session import SessionLocal
from app.models import AgentLog, GenerationTask, LLMCall
from app.services.task_events import publish_task_event

_DEFAULT_MODEL_PRICING = {
    "gpt-5.5": {"in": 1.25, "out": 10.0},
}
_TRANSIENT_STATUS_CODES = {408, 409, 429, 500, 502, 503, 504, 520, 522, 524}
_TRANSIENT_ERROR_CODES = {"rate_limit_exceeded", "server_error", "vector_store_timeout"}
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


def _estimate_tokens(text_chars: int) -> int:
    return max(1, round(max(0, text_chars) / 4))


def _estimate_prompt_tokens(system: str, user: str) -> int:
    return _estimate_tokens(len(system or "") + len(user or ""))


def _pricing() -> dict:
    raw = (settings.MODEL_PRICING_JSON or "").strip()
    if not raw:
        return _DEFAULT_MODEL_PRICING
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else _DEFAULT_MODEL_PRICING
    except json.JSONDecodeError:
        return _DEFAULT_MODEL_PRICING


def _price_for(model: str, prompt_tokens: int, completion_tokens: int) -> Decimal | None:
    table = _pricing()
    price = table.get(model) or table.get(model.split(":")[0])
    if not isinstance(price, dict):
        return None
    try:
        input_per_million = Decimal(str(price["in"]))
        output_per_million = Decimal(str(price["out"]))
    except (KeyError, InvalidOperation):
        return None
    cost = (
        Decimal(prompt_tokens) * input_per_million
        + Decimal(completion_tokens) * output_per_million
    ) / Decimal(1_000_000)
    return cost.quantize(Decimal("0.000001"))


def _record_call(result: LLMResult, *, retried: bool = False) -> None:
    ctx = get_context()
    task_id = ctx.get("task_id")
    step_id = ctx.get("step_id")
    if not task_id and not step_id:
        return
    db = SessionLocal()
    try:
        db.add(
            LLMCall(
                task_id=task_id,
                step_id=step_id,
                model=result.model,
                prompt_tokens=result.prompt_tokens,
                completion_tokens=result.completion_tokens,
                total_tokens=result.total_tokens,
                cached_tokens=result.cached_tokens,
                latency_ms=result.latency_ms,
                retried=retried,
                cost_usd=result.cost_usd,
            )
        )
        if task_id and result.cost_usd is not None:
            task = db.get(GenerationTask, task_id)
            if task:
                task.cost_usd = (task.cost_usd or Decimal("0")) + result.cost_usd
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()
    finally:
        db.close()


def _record_stream_progress(line: str, payload: dict | None = None) -> None:
    ctx = get_context()
    task_id = ctx.get("task_id")
    step_id = ctx.get("step_id")
    if not step_id:
        return
    db = SessionLocal()
    try:
        seq = (
            db.query(func.count(AgentLog.id))
            .filter(AgentLog.step_id == step_id)
            .scalar()
            or 0
        )
        db.add(
            AgentLog(
                step_id=step_id,
                seq=int(seq),
                line=line,
                payload_json=json.dumps(payload, ensure_ascii=False) if payload else None,
            )
        )
        db.commit()
        if task_id:
            publish_task_event(task_id, "log_appended")
    except Exception:  # noqa: BLE001
        db.rollback()
    finally:
        db.close()


def record_usage(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    latency_ms: int,
    *,
    retried: bool = False,
    cached_tokens: int = 0,
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
        cost_usd=_price_for(model, prompt_tokens, completion_tokens),
        cached_tokens=int(cached_tokens or 0),
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
) -> LLMResult:
    requested_model = model or settings.MODEL_NAME
    input_text = user
    if response_format is not None and response_format.get("type") == "json_object":
        input_text = (
            f"{user}\n\n"
            "Return only a valid JSON object. Do not include markdown fences or extra text."
        )
    kwargs: dict = {
        "model": requested_model,
        "instructions": system,
        "input": input_text,
        "stream": True,
        "store": False,
    }
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
                "timeout": timeout,
            },
        )

    max_retries = max(0, int(settings.OPENAI_MAX_RETRIES or 0))
    partial_min_chars = max(0, int(settings.OPENAI_PARTIAL_STREAM_MIN_CHARS or 0))
    retried = False
    for attempt in range(max_retries + 1):
        start = time.perf_counter()
        text_parts: list[str] = []
        done_text = ""
        completed_response = None
        streamed_chars = 0
        try:
            if trace_recorder:
                trace_recorder.record(
                    "llm_input",
                    {"attempt": attempt + 1, "request": kwargs},
                )
            _record_stream_progress("stream_tokens=0")
            stream = _client(timeout=timeout).responses.create(**kwargs)
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
            will_retry = attempt < max_retries and _retryable(exc)
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
                if trace_recorder:
                    trace_recorder.record(
                        "run_end",
                        {"status": "failed", "attempts": attempt + 1},
                    )
                raise
            retried = True
            time.sleep(_retry_delay(attempt))
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
    if latency_ms >= int(_STREAM_PROGRESS_INTERVAL_SECONDS * 1000):
        _record_stream_progress(f"stream_tokens={completion_tokens or _estimate_tokens(len(text))}")
    actual_model = str(getattr(completed_response, "model", None) or requested_model)
    if prompt_tokens:
        # 0% 也要落一行：一次性调用的命中率此前无人观测，"零"与"没测"必须可区分。
        cache_pct = cached_tokens * 100 // prompt_tokens
        _record_stream_progress(
            f"prompt cache: {cached_tokens}/{prompt_tokens} read ({cache_pct}%)",
            payload={
                "type": "usage",
                "input_tokens": prompt_tokens,
                "output_tokens": completion_tokens,
                "total_tokens": total_tokens,
                "cached_tokens": cached_tokens,
                "requests": 1,
                "cache_percent": cache_pct,
            },
        )
    result = LLMResult(
        text=text,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        model=actual_model,
        latency_ms=latency_ms,
        cost_usd=_price_for(actual_model, prompt_tokens, completion_tokens),
        cached_tokens=cached_tokens,
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
