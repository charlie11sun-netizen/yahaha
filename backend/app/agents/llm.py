from __future__ import annotations

import json
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from openai import OpenAI

from app.core.config import settings
from app.core.telemetry import get_context
from app.db.session import SessionLocal
from app.models import GenerationTask, LLMCall

_DEFAULT_MODEL_PRICING = {
    "gpt-5.5": {"in": 1.25, "out": 10.0},
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

    def __iter__(self):
        # Backward compatible with existing `raw, tokens = llm.chat(...)` calls.
        yield self.text
        yield self.total_tokens


def _client(*, timeout: int | None = None) -> OpenAI:
    return OpenAI(
        api_key=settings.OPENAI_API_KEY,
        base_url=settings.OPENAI_BASE_URL,
        timeout=timeout or settings.OPENAI_TIMEOUT,
    )


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


def chat(
    system: str,
    user: str,
    temperature: float | None = None,
    max_tokens: int | None = None,
    *,
    model: str | None = None,
    timeout: int | None = None,
    response_format: dict | None = None,
) -> LLMResult:
    requested_model = model or settings.MODEL_NAME
    kwargs: dict = {
        "model": requested_model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    if temperature is not None:
        kwargs["temperature"] = temperature
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    if response_format is not None:
        kwargs["response_format"] = response_format

    start = time.perf_counter()
    resp = _client(timeout=timeout).chat.completions.create(**kwargs)
    latency_ms = int((time.perf_counter() - start) * 1000)
    text = (resp.choices[0].message.content or "").strip()
    usage = getattr(resp, "usage", None)
    prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0) if usage else 0
    completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0) if usage else 0
    total_tokens = int(getattr(usage, "total_tokens", 0) or 0) if usage else 0
    if total_tokens <= 0:
        total_tokens = prompt_tokens + completion_tokens
    actual_model = str(getattr(resp, "model", None) or requested_model)
    result = LLMResult(
        text=text,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        model=actual_model,
        latency_ms=latency_ms,
        cost_usd=_price_for(actual_model, prompt_tokens, completion_tokens),
    )
    _record_call(result)
    return result
