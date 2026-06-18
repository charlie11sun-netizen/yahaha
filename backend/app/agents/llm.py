"""模型调用层（OpenAI 兼容，如 Yahaha 提供的 GPT-5.5）。

只发 model + messages（可选 temperature/max_tokens），最大化兼容各家 OpenAI 兼容端点。
换 provider / 模型只改 .env 的 OPENAI_BASE_URL / MODEL_NAME。
"""
from openai import OpenAI

from app.core.config import settings


def _client() -> OpenAI:
    return OpenAI(api_key=settings.OPENAI_API_KEY, base_url=settings.OPENAI_BASE_URL, timeout=settings.OPENAI_TIMEOUT)


def chat(system: str, user: str, temperature: float | None = None, max_tokens: int | None = None) -> tuple[str, int]:
    kwargs: dict = {
        "model": settings.MODEL_NAME,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    if temperature is not None:
        kwargs["temperature"] = temperature
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens

    resp = _client().chat.completions.create(**kwargs)
    text = (resp.choices[0].message.content or "").strip()
    usage = getattr(resp, "usage", None)
    tokens = getattr(usage, "total_tokens", 0) if usage else 0
    return text, int(tokens or 0)
