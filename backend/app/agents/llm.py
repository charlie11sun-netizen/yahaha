from __future__ import annotations

import json
import logging
import time

from app.agents import detailed_trace, llm_accounting, llm_cache, llm_provider
from app.agents.llm_accounting import LLMResult
from app.agents.llm_provider import LLMResponseError
from app.core.config import settings
from app.core.telemetry import get_context
from app.db.session import SessionLocal
from app.services.task_events import publish_task_event

# Compatibility facade: callers keep importing ``app.agents.llm`` while the
# provider, cache, and accounting implementations live in focused modules.
logger = logging.getLogger(__name__)

_STREAM_PROGRESS_INTERVAL_SECONDS = llm_provider.STREAM_PROGRESS_INTERVAL_SECONDS
_client = llm_provider.client
_status_code = llm_provider.status_code
_retryable = llm_provider.retryable
_retry_delay = llm_provider.retry_delay
_close_sync_resource = llm_provider.close_sync_resource
_stream_failure_payload = llm_provider.stream_failure_payload
_extract_response_text = llm_provider.extract_response_text
_event_error = llm_provider.event_error

_estimate_tokens = llm_accounting.estimate_tokens
_estimate_prompt_tokens = llm_accounting.estimate_prompt_tokens
_pricing = llm_accounting._pricing
_price_for = llm_accounting.price_for
_ledger_idempotency_constraint = llm_accounting.ledger_idempotency_constraint

prompt_cache_key = llm_cache.prompt_cache_key
_supports_explicit_prompt_cache = llm_cache.supports_explicit_prompt_cache
_explicit_cache_input = llm_cache.explicit_cache_input


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
    previous_response_id: str | None = None,
    request_index: int | None = None,
    status: str = "completed",
    error_code: str | None = None,
) -> bool:
    return llm_accounting.persist_call(
        result,
        session_factory=SessionLocal,
        context=get_context(),
        logger=logger,
        retried=retried,
        task_id=task_id,
        step_id=step_id,
        run_id=run_id,
        agent=agent,
        workflow_name=workflow_name,
        provider_response_id=provider_response_id,
        previous_response_id=previous_response_id,
        request_index=request_index,
        status=status,
        error_code=error_code,
    )


def _record_call(
    result: LLMResult,
    *,
    retried: bool = False,
    previous_response_id: str | None = None,
) -> bool:
    return _persist_call(
        result, retried=retried, previous_response_id=previous_response_id
    )


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
    previous_response_id: str | None = None,
    request_index: int,
    status: str = "completed",
    error_code: str | None = None,
    retried: bool = False,
) -> LLMResult:
    """Persist exactly one Agents SDK provider response.

    Unlike the legacy aggregate-at-run-end path, this survives MaxTurns and is
    safe when a streamed event is replayed.  ``llm_calls`` is the usage ledger;
    task and step counters are updated only if the ledger insert succeeds.
    ``retried`` marks a response that completed after a stream retry; failed
    attempts without provider usage remain represented by retry trace events.
    """
    result = llm_accounting.response_usage_result(
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cached_tokens=cached_tokens,
        cache_write_tokens=cache_write_tokens,
        latency_ms=latency_ms,
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
        previous_response_id=previous_response_id,
        request_index=request_index,
        status=status,
        error_code=error_code,
        retried=retried,
    )
    return result


def _record_stream_progress(line: str, payload: dict | None = None) -> None:
    llm_accounting.record_stream_progress(
        line,
        payload,
        session_factory=SessionLocal,
        context=get_context(),
        publish_task_event=publish_task_event,
        logger=logger,
        sleep=time.sleep,
    )


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
    result = llm_accounting.usage_result(
        model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        latency_ms=latency_ms,
        cached_tokens=cached_tokens,
        cache_write_tokens=cache_write_tokens,
    )
    _record_call(result, retried=retried)
    return result


def _partial_stream_result(
    *,
    text: str,
    requested_model: str,
    system: str,
    input_text: str,
    start: float,
    retried: bool,
    context_chars: int = 0,
    previous_response_id: str | None = None,
) -> LLMResult:
    latency_ms = int((time.perf_counter() - start) * 1000)
    prompt_tokens = _estimate_prompt_tokens(system, input_text) + (
        _estimate_tokens(context_chars) if context_chars else 0
    )
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
    _record_call(result, retried=retried, previous_response_id=previous_response_id)
    return result


def _verify_provider_echo(kwargs: dict, completed_response: object) -> None:
    """Warn when the provider silently drops conversation-state parameters.

    The production gateway proved able to strip ``store``/``previous_response_id``
    without any error, which turned server-side chaining into an invisible
    no-op for weeks. The response echoes both fields, so one comparison per
    call makes that drift observable in task logs the day it happens.
    """
    sent_previous = kwargs.get("previous_response_id")
    echoed_previous = getattr(completed_response, "previous_response_id", None)
    echoed_store = getattr(completed_response, "store", None)
    problems = []
    if sent_previous and echoed_previous != sent_previous:
        problems.append(
            f"previous_response_id sent={sent_previous} echoed={echoed_previous or 'null'}"
        )
    if kwargs.get("store") and echoed_store is False:
        problems.append("store=true refused (response echoed store=false)")
    if not problems:
        return
    line = (
        "WARNING provider dropped conversation state: "
        + "; ".join(problems)
        + " — server-side chaining is a no-op on this gateway"
    )
    logger.warning(line)
    _record_stream_progress(
        line,
        payload={
            "type": "chain_echo_mismatch",
            "sent_previous_response_id": sent_previous,
            "echoed_previous_response_id": echoed_previous,
            "sent_store": bool(kwargs.get("store")),
            "echoed_store": echoed_store,
        },
    )


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
    previous_response_id: str | None = None,
    store: bool = False,
    context_items: list[dict] | None = None,
    chained_from_response_id: str | None = None,
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
    if context_items:
        # Client-side conversation chaining: the prior turns are replayed as
        # explicit input items because the gateway silently drops server-side
        # state (store/previous_response_id). Mixing both would double the
        # context on any provider that honors previous_response_id.
        if previous_response_id:
            raise ValueError(
                "context_items and previous_response_id are mutually exclusive"
            )
        if cache_prefix is not None:
            raise ValueError(
                "context_items cannot be combined with explicit cache_prefix input"
            )
        prior = [
            {"role": str(item["role"]), "content": str(item["content"])}
            for item in context_items
        ]
        new_turn = (
            model_input
            if isinstance(model_input, list)
            else [{"role": "user", "content": input_text}]
        )
        model_input = [*prior, *new_turn]
    context_chars = sum(
        len(str(item.get("content") or "")) for item in (context_items or [])
    )
    # Conversation predecessor for the usage ledger: explicit lineage from
    # client-side chaining, or the server-side chaining parameter itself.
    chain_lineage_id = chained_from_response_id or previous_response_id
    kwargs: dict = {
        "model": requested_model,
        "instructions": system,
        "input": model_input,
        "stream": True,
        "store": bool(store),
    }
    if previous_response_id:
        # Responses API conversation chaining requires the preceding response
        # to remain addressable. Callers that provide an id therefore always
        # opt into stored responses, even if they omitted ``store=True``.
        kwargs["previous_response_id"] = previous_response_id
        kwargs["store"] = True
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
    # require_code_context=False: planning/QA calls must be traceable too —
    # the chain rebuild was unverifiable while stages 1-3 never reached
    # agent_trace_events (request kwargs are the only place the replayed
    # transcript and chain ids are recorded verbatim).
    trace_recorder = detailed_trace.create_recorder(
        source="responses_api",
        agent=context.get("agent") or "GameCodeAgent",
        model=requested_model,
        require_code_context=False,
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
                        context_chars=context_chars,
                        previous_response_id=chain_lineage_id,
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
                    context_chars=context_chars,
                    previous_response_id=chain_lineage_id,
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
                        context_chars=context_chars,
                        previous_response_id=chain_lineage_id,
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
    _verify_provider_echo(kwargs, completed_response)
    if prompt_tokens:
        # 0% 也要落一行：一次性调用的命中率此前无人观测，"零"与"没测"必须可区分。
        cache_pct = cached_tokens * 100 // prompt_tokens
        cache_line = f"prompt cache: {cached_tokens}/{prompt_tokens} read ({cache_pct}%)"
        if cache_write_tokens:
            cache_line += f", {cache_write_tokens} written"
        if chain_lineage_id:
            cache_line += f"; chained from {chain_lineage_id}"
            if context_items:
                cache_line += f" ({len(context_items)} replayed message(s))"
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
                "previous_response_id": chain_lineage_id,
                "context_messages": len(context_items or []),
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
    _record_call(result, retried=retried, previous_response_id=chain_lineage_id)
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
