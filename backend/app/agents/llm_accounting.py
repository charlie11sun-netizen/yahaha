from __future__ import annotations

"""LLM usage results, pricing, progress logs, and durable ledger accounting."""

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import case, func
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.models import AgentStep, GenerationTask, LLMCall
from app.services.agent_logs import append_agent_log

_DEFAULT_MODEL_PRICING = {
    "gpt-5.5": {"in": 1.25, "out": 10.0},
}
_LEDGER_IDEMPOTENCY_CONSTRAINTS = {
    "uq_llm_calls_provider_response_id",
    "uq_llm_calls_run_request",
}


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
    cache_read_reported: bool = False
    cache_write_reported: bool = False
    provider_response_id: str | None = None

    def __iter__(self):
        # Backward compatible with existing `raw, tokens = llm.chat(...)` calls.
        yield self.text
        yield self.total_tokens


def estimate_tokens(text_chars: int) -> int:
    return max(1, round(max(0, text_chars) / 4))


def estimate_prompt_tokens(system: str, user: str) -> int:
    return estimate_tokens(len(system or "") + len(user or ""))


def _pricing() -> dict:
    raw = (settings.MODEL_PRICING_JSON or "").strip()
    if not raw:
        return _DEFAULT_MODEL_PRICING
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else _DEFAULT_MODEL_PRICING
    except json.JSONDecodeError:
        return _DEFAULT_MODEL_PRICING


def price_for(
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
    try:
        cached_input_per_million = Decimal(str(price.get("cached_in", price["in"])))
    except (KeyError, InvalidOperation):
        cached_input_per_million = input_per_million
    try:
        cache_write_per_million = Decimal(
            str(price.get("cache_write_in", price["in"]))
        )
    except (KeyError, InvalidOperation):
        cache_write_per_million = input_per_million
    cost = (
        Decimal(regular_uncached_tokens) * input_per_million
        + Decimal(cache_write_tokens) * cache_write_per_million
        + Decimal(cached_tokens) * cached_input_per_million
        + Decimal(completion_tokens) * output_per_million
    ) / Decimal(1_000_000)
    return cost.quantize(Decimal("0.000001"))


def ledger_idempotency_constraint(exc: IntegrityError) -> str | None:
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
    if "unique constraint failed: llm_calls.run_id, llm_calls.request_index" in message:
        return "uq_llm_calls_run_request"
    return None


def persist_call(
    result: LLMResult,
    *,
    session_factory: Callable[[], Any],
    context: Mapping[str, Any],
    logger: Any,
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
    cache_metadata: Mapping[str, Any] | None = None,
) -> bool:
    task_id = task_id or context.get("task_id")
    step_id = step_id or context.get("step_id")
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
    cache_metadata = dict(cache_metadata or {})
    provider_response_id = provider_response_id or result.provider_response_id
    db = session_factory()
    try:
        step = (
            db.get(AgentStep, step_id)
            if step_id and callable(getattr(db, "get", None))
            else None
        )
        if step and not task_id:
            task_id = step.task_id
        task = (
            db.get(GenerationTask, task_id)
            if task_id and callable(getattr(db, "get", None))
            else None
        )
        call = LLMCall(
            task_id=task_id,
            step_id=step_id,
            run_id=run_id,
            agent=agent or context.get("agent"),
            workflow_name=workflow_name,
            provider_response_id=provider_response_id,
            previous_response_id=previous_response_id,
            request_index=request_index,
            status=status,
            error_code=error_code,
            model=result.model,
            provider=cache_metadata.get("provider") or "openai",
            provider_route=cache_metadata.get("provider_route"),
            prompt_version=cache_metadata.get("prompt_version")
            or (step.prompt_version if step else None),
            contract_hash=cache_metadata.get("contract_hash")
            or (step.contract_hash if step else None)
            or (task.contract_hash if task else None),
            contract_revision=cache_metadata.get("contract_revision")
            or (task.contract_revision if task else None),
            prompt_cache_key_hash=cache_metadata.get("prompt_cache_key_hash"),
            prompt_cache_namespace=cache_metadata.get("prompt_cache_namespace"),
            prompt_cache_mode=cache_metadata.get("prompt_cache_mode"),
            prompt_cache_ttl=cache_metadata.get("prompt_cache_ttl"),
            cache_prefix_hash=cache_metadata.get("cache_prefix_hash"),
            toolset_hash=cache_metadata.get("toolset_hash"),
            cache_bypass_reason=cache_metadata.get("cache_bypass_reason"),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cached_tokens=cached_tokens,
            cache_write_tokens=cache_write_tokens,
            cache_read_reported=bool(result.cache_read_reported),
            cache_write_reported=bool(result.cache_write_reported),
            latency_ms=max(0, int(result.latency_ms or 0)),
            retried=retried,
            cost_usd=result.cost_usd,
        )
        db.add(call)
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
        if ledger_idempotency_constraint(exc):
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


def response_usage_result(
    *,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    cached_tokens: int = 0,
    cache_write_tokens: int = 0,
    cache_read_reported: bool = False,
    cache_write_reported: bool = False,
    latency_ms: int = 0,
    provider_response_id: str | None = None,
) -> LLMResult:
    prompt_tokens = max(0, int(prompt_tokens or 0))
    completion_tokens = max(0, int(completion_tokens or 0))
    cached_tokens = min(max(0, int(cached_tokens or 0)), prompt_tokens)
    cache_write_tokens = min(
        max(0, int(cache_write_tokens or 0)),
        max(0, prompt_tokens - cached_tokens),
    )
    return LLMResult(
        text="",
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
        model=model,
        latency_ms=max(0, int(latency_ms or 0)),
        cost_usd=price_for(
            model,
            prompt_tokens,
            completion_tokens,
            cached_tokens=cached_tokens,
            cache_write_tokens=cache_write_tokens,
        ),
        cached_tokens=cached_tokens,
        cache_write_tokens=cache_write_tokens,
        cache_read_reported=bool(cache_read_reported),
        cache_write_reported=bool(cache_write_reported),
        provider_response_id=provider_response_id,
    )


def usage_result(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    latency_ms: int,
    *,
    cached_tokens: int = 0,
    cache_write_tokens: int = 0,
    cache_read_reported: bool = False,
    cache_write_reported: bool = False,
) -> LLMResult:
    prompt_tokens = int(prompt_tokens or 0)
    completion_tokens = int(completion_tokens or 0)
    return LLMResult(
        text="",
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
        model=model,
        latency_ms=int(latency_ms or 0),
        cost_usd=price_for(
            model,
            prompt_tokens,
            completion_tokens,
            cached_tokens=cached_tokens,
            cache_write_tokens=cache_write_tokens,
        ),
        cached_tokens=int(cached_tokens or 0),
        cache_write_tokens=int(cache_write_tokens or 0),
        cache_read_reported=bool(cache_read_reported),
        cache_write_reported=bool(cache_write_reported),
    )


def cache_observability_metadata(
    *,
    session_factory: Callable[[], Any],
    task_id: str,
    step_id: str | None = None,
    logger: Any,
) -> dict[str, Any]:
    """Aggregate durable LLM cache accounting into bounded Opik metadata."""
    db = session_factory()
    try:
        query = db.query(
            func.count(LLMCall.id),
            func.coalesce(func.sum(LLMCall.prompt_tokens), 0),
            func.coalesce(func.sum(LLMCall.completion_tokens), 0),
            func.coalesce(func.sum(LLMCall.cached_tokens), 0),
            func.coalesce(func.sum(LLMCall.cache_write_tokens), 0),
            func.coalesce(func.sum(LLMCall.latency_ms), 0),
            func.coalesce(func.avg(LLMCall.latency_ms), 0),
            func.coalesce(func.sum(LLMCall.cost_usd), 0),
            func.coalesce(
                func.sum(case((LLMCall.retried.is_(True), 1), else_=0)), 0
            ),
            func.coalesce(
                func.sum(case((LLMCall.cached_tokens > 0, 1), else_=0)), 0
            ),
            func.coalesce(
                func.sum(case((LLMCall.cache_read_reported.is_(True), 1), else_=0)), 0
            ),
            func.coalesce(
                func.sum(case((LLMCall.cache_write_reported.is_(True), 1), else_=0)), 0
            ),
        ).filter(LLMCall.task_id == task_id)
        if step_id:
            query = query.filter(LLMCall.step_id == step_id)
        row = query.one()
        call_count = int(row[0] or 0)
        if not call_count:
            return {}
        prompt_tokens = int(row[1] or 0)
        completion_tokens = int(row[2] or 0)
        cached_tokens = min(int(row[3] or 0), prompt_tokens)
        cache_write_tokens = max(0, int(row[4] or 0))
        uncached_tokens = max(0, prompt_tokens - cached_tokens)
        metrics = {
            "call_count": call_count,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "cached_tokens": cached_tokens,
            "cache_write_tokens": cache_write_tokens,
            "uncached_tokens": uncached_tokens,
            "cache_hit_rate": round(cached_tokens / prompt_tokens, 6)
            if prompt_tokens
            else None,
            "cache_write_rate": round(cache_write_tokens / uncached_tokens, 6)
            if uncached_tokens
            else None,
            "latency_ms_total": int(row[5] or 0),
            "latency_ms_avg": round(float(row[6] or 0), 3),
            "cost_usd": float(row[7] or 0),
            "retry_count": int(row[8] or 0),
            "cache_hit_call_count": int(row[9] or 0),
            "cache_read_reported_count": int(row[10] or 0),
            "cache_write_reported_count": int(row[11] or 0),
        }
        return {
            "llm_call_count": metrics["call_count"],
            "llm_prompt_tokens": metrics["prompt_tokens"],
            "llm_completion_tokens": metrics["completion_tokens"],
            "llm_total_tokens": metrics["total_tokens"],
            "llm_cached_tokens": metrics["cached_tokens"],
            "llm_cache_write_tokens": metrics["cache_write_tokens"],
            "llm_uncached_tokens": metrics["uncached_tokens"],
            "llm_cache_hit_rate": metrics["cache_hit_rate"],
            "llm_cache_write_rate": metrics["cache_write_rate"],
            "llm_latency_ms_avg": metrics["latency_ms_avg"],
            "llm_cost_usd": metrics["cost_usd"],
            "llm_retry_count": metrics["retry_count"],
            "llm_cache_hit_call_count": metrics["cache_hit_call_count"],
            "llm_cache_read_reported_count": metrics[
                "cache_read_reported_count"
            ],
            "llm_cache_write_reported_count": metrics[
                "cache_write_reported_count"
            ],
            "llm_cache_metrics": metrics,
        }
    except Exception:  # noqa: BLE001 - observability aggregation must fail open
        logger.exception(
            "LLM cache observability aggregation failed",
            extra={"generation_task_id": task_id, "step_id": step_id},
        )
        return {}
    finally:
        db.close()


def record_stream_progress(
    line: str,
    payload: dict | None,
    *,
    session_factory: Callable[[], Any],
    context: Mapping[str, Any],
    publish_task_event: Callable[[str, str], Any],
    logger: Any,
    sleep: Callable[[float], None],
) -> None:
    task_id = context.get("task_id")
    step_id = context.get("step_id")
    append_agent_log(
        line,
        step_id=step_id,
        task_id=task_id,
        payload=payload,
        level="info",
        session_factory=session_factory,
        publish_task_event=publish_task_event,
        logger=logger,
        sleep=sleep,
    )
