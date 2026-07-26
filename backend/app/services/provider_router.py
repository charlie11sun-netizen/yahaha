"""Modality-aware routing for generated game assets.

The pipeline depends on this small interface, not on a specific vendor SDK.
Adding Tongyi/Doubao adapters later only requires registering another adapter;
LangGraph nodes and artifact publishing stay unchanged.
"""
from __future__ import annotations

import base64
import html
import io
import json
import wave
from dataclasses import dataclass
from typing import Literal, Protocol

import httpx

from app.core.config import settings

Modality = Literal["image", "audio", "video"]


class ProviderConfigurationError(RuntimeError):
    pass


class ProviderGenerationError(RuntimeError):
    pass


class ProviderStreamProtocolError(ProviderGenerationError):
    """The provider accepted streaming but did not return a valid final event.

    Retrying this automatically can generate and charge for the same image
    twice, so callers should surface it without their normal transient retry.
    """


class _ProviderStreamingUnsupported(RuntimeError):
    """Internal signal for a fast, safe fallback to the synchronous request."""


@dataclass(frozen=True)
class ProviderConfig:
    modality: Modality
    provider: str
    api_key: str
    base_url: str
    model: str


@dataclass(frozen=True)
class MediaRequest:
    modality: Modality
    prompt: str
    size: str = "1024x1024"
    duration_seconds: int = 4
    # 逐提供商的附加载荷（如 gpt-image 的 {"background": "transparent"}）。
    # openai 兼容网关会忽略不认识的字段；FAIL_OPEN 下即使拒绝也只是跳过该素材。
    extra: dict | None = None


@dataclass(frozen=True)
class GeneratedMedia:
    content: bytes
    content_type: str
    extension: str
    provider: str
    model: str


class ProviderAdapter(Protocol):
    def generate(self, request: MediaRequest, config: ProviderConfig) -> GeneratedMedia: ...


def _safe_svg_label(prompt: str) -> str:
    compact = " ".join(str(prompt or "game asset").split())[:72]
    return html.escape(compact or "game asset")


class LocalPlaceholderAdapter:
    """Offline deterministic fallback used by tests and local development."""

    def generate(self, request: MediaRequest, config: ProviderConfig) -> GeneratedMedia:
        if request.modality == "image":
            if str((request.extra or {}).get("background") or "").lower() == "transparent":
                # Sprite sheets and tilesets must be sliceable in offline/test
                # mode too. A vector label card cannot exercise the real alpha,
                # grid, and checkpoint pipeline, so emit deterministic RGBA art.
                from PIL import Image, ImageDraw

                image = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
                draw = ImageDraw.Draw(image)
                palette = [
                    "#22d3ee",
                    "#a78bfa",
                    "#f472b6",
                    "#facc15",
                    "#34d399",
                    "#fb7185",
                ]
                cell = 256
                tileset = "tileset" in str(request.prompt or "").lower()
                for index in range(16):
                    col, row = index % 4, index // 4
                    x0, y0 = col * cell, row * cell
                    color = palette[index % len(palette)]
                    if tileset and row < 2:
                        draw.rounded_rectangle(
                            (x0 + 8, y0 + 8, x0 + cell - 8, y0 + cell - 8),
                            radius=24,
                            fill=color,
                            outline="#0f172a",
                            width=10,
                        )
                    else:
                        draw.ellipse(
                            (x0 + 48, y0 + 40, x0 + cell - 48, y0 + cell - 40),
                            fill=color,
                            outline="#0f172a",
                            width=12,
                        )
                        draw.rectangle(
                            (x0 + 94, y0 + 88, x0 + 162, y0 + 176),
                            fill="#f8fafc",
                        )
                output = io.BytesIO()
                image.save(output, format="PNG")
                return GeneratedMedia(
                    output.getvalue(),
                    "image/png",
                    ".png",
                    "local",
                    "placeholder-rgba-grid",
                )
            label = _safe_svg_label(request.prompt)
            svg = (
                '<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1024" viewBox="0 0 1024 1024">'
                '<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
                '<stop stop-color="#111827"/><stop offset="1" stop-color="#7c3aed"/></linearGradient></defs>'
                '<rect width="1024" height="1024" fill="url(#g)"/>'
                '<circle cx="512" cy="430" r="220" fill="#22d3ee" opacity=".18"/>'
                f'<text x="512" y="540" text-anchor="middle" fill="white" font-size="34" '
                f'font-family="sans-serif">{label}</text></svg>'
            )
            return GeneratedMedia(svg.encode("utf-8"), "image/svg+xml", ".svg", "local", "placeholder-svg")
        if request.modality == "audio":
            frames = max(1, min(request.duration_seconds, 10)) * 8_000
            buf = io.BytesIO()
            with wave.open(buf, "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(8_000)
                wav.writeframes(b"\x00\x00" * frames)
            return GeneratedMedia(buf.getvalue(), "audio/wav", ".wav", "local", "silent-wav")
        raise ProviderGenerationError("local provider does not synthesize video")


def _sticky_session_header() -> dict[str, str]:
    """sub2api-style gateways route media calls to upstream accounts only by
    explicit session signals (header session_id / conversation_id); without one
    every image call may land on a different subscription account. Real OpenAI
    ignores the header, so sending it is always safe."""
    try:
        from app.core.telemetry import get_context

        task_scope = str(get_context().get("task_id") or "").replace("-", "")[:12]
    except Exception:  # noqa: BLE001 - affinity is best-effort, never fatal
        return {}
    if not task_scope:
        return {}
    return {"session_id": f"gameweave:assets:{task_scope}"}


def _response_detail(response: httpx.Response | None) -> str:
    """Extract a compact upstream error body; httpx omits it from str(exc)."""
    if response is None:
        return ""
    try:
        response.read()
    except Exception:  # noqa: BLE001 - diagnostics only
        pass
    try:
        text = response.text
    except Exception:  # noqa: BLE001 - diagnostics only
        return ""
    return " ".join((text or "").split())[:300]


class OpenAICompatibleAdapter:
    """Small HTTP adapter for OpenAI-style media endpoints."""

    _PATHS = {
        "image": "/images/generations",
        "audio": "/audio/speech",
        "video": "/videos/generations",
    }

    def generate(self, request: MediaRequest, config: ProviderConfig) -> GeneratedMedia:
        base = config.base_url.rstrip("/")
        headers = {"Authorization": f"Bearer {config.api_key}", **_sticky_session_header()}
        if request.modality == "image":
            payload = {
                "model": config.model,
                "prompt": request.prompt,
                "size": request.size,
                "response_format": "b64_json",
            }
        elif request.modality == "audio":
            payload = {
                "model": config.model,
                "input": request.prompt,
                "voice": "alloy",
                "response_format": "wav",
            }
        else:
            payload = {
                "model": config.model,
                "prompt": request.prompt,
                "duration": request.duration_seconds,
            }
        if request.extra:
            payload.update(request.extra)
        if request.modality == "image" and settings.ASSET_IMAGE_STREAMING_ENABLED:
            try:
                return self._generate_streaming_image(
                    base + self._PATHS[request.modality],
                    headers,
                    payload,
                    config,
                )
            except _ProviderStreamingUnsupported:
                # A prompt validation error must never land here. Only endpoint /
                # media-type errors that indicate the streaming extension itself
                # is unsupported are eligible for a synchronous retry.
                pass
        return self._generate_sync(request, config, base, headers, payload)

    def _generate_sync(
        self,
        request: MediaRequest,
        config: ProviderConfig,
        base: str,
        headers: dict[str, str],
        payload: dict,
    ) -> GeneratedMedia:
        try:
            response = httpx.post(
                base + self._PATHS[request.modality],
                headers=headers,
                json=payload,
                timeout=settings.ASSET_PROVIDER_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = _response_detail(exc.response)
            suffix = f" | body: {detail}" if detail else ""
            raise ProviderGenerationError(
                f"{request.modality} provider request failed: {exc}{suffix}"
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderGenerationError(f"{request.modality} provider request failed: {exc}") from exc
        return self._decode_response(response, request.modality, config)

    def _generate_streaming_image(
        self,
        url: str,
        headers: dict[str, str],
        payload: dict,
        config: ProviderConfig,
    ) -> GeneratedMedia:
        stream_payload = dict(payload)
        stream_payload["stream"] = True
        stream_payload["partial_images"] = max(
            1,
            min(3, int(settings.ASSET_IMAGE_PARTIAL_IMAGES)),
        )
        stream_headers = {**headers, "Accept": "text/event-stream"}
        try:
            with httpx.stream(
                "POST",
                url,
                headers=stream_headers,
                json=stream_payload,
                timeout=settings.ASSET_PROVIDER_TIMEOUT_SECONDS,
            ) as response:
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    # These statuses commonly mean the compatible gateway does
                    # not implement the streaming extension. They arrive before
                    # generation starts and are safe to retry synchronously.
                    if self._streaming_unsupported(response):
                        raise _ProviderStreamingUnsupported from exc
                    raise

                content_type = response.headers.get("content-type", "").lower()
                if "text/event-stream" not in content_type:
                    # Some gateways ignore `stream` and return the ordinary JSON
                    # result. Accept that result instead of generating it again.
                    response.read()
                    return self._decode_response(response, "image", config)
                return self._decode_image_stream(response, config)
        except _ProviderStreamingUnsupported:
            raise
        except ProviderGenerationError:
            raise
        except httpx.HTTPStatusError as exc:
            detail = _response_detail(exc.response)
            suffix = f" | body: {detail}" if detail else ""
            raise ProviderGenerationError(f"image provider stream failed: {exc}{suffix}") from exc
        except httpx.HTTPError as exc:
            raise ProviderGenerationError(f"image provider stream failed: {exc}") from exc

    @staticmethod
    def _streaming_unsupported(response: httpx.Response) -> bool:
        if response.status_code in {404, 405, 415, 422, 501}:
            return True
        if response.status_code != 400:
            return False
        # 400 is ambiguous: it may be an unsupported stream parameter (safe to
        # fall back) or a bad prompt/request (not safe to generate again). Only
        # accept an explicit parameter-capability error.
        try:
            body = response.read().decode("utf-8", "replace").lower()
        except httpx.HTTPError:
            return False
        mentions_field = "stream" in body or "partial_images" in body
        capability_error = any(
            marker in body
            for marker in ("unknown", "unsupported", "unrecognized", "not allowed", "extra field")
        )
        return mentions_field and capability_error

    def _decode_image_stream(
        self,
        response: httpx.Response,
        config: ProviderConfig,
    ) -> GeneratedMedia:
        final_encoded: str | None = None
        data_lines: list[str] = []

        def consume_event() -> None:
            nonlocal final_encoded
            if not data_lines:
                return
            raw = "\n".join(data_lines).strip()
            data_lines.clear()
            if not raw or raw == "[DONE]":
                return
            try:
                event = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ProviderStreamProtocolError("image provider returned invalid SSE JSON") from exc
            if event.get("type") != "image_generation.completed":
                return
            item = (event.get("data") or [event])[0]
            final_encoded = item.get("b64_json") or item.get("b64") or item.get("base64")

        for line in response.iter_lines():
            line = line.lstrip("\ufeff")
            if not line:
                consume_event()
            elif line.startswith("data:"):
                data_lines.append(line[5:].lstrip())
        consume_event()

        if not final_encoded:
            raise ProviderStreamProtocolError(
                "image provider closed the SSE stream without image_generation.completed"
            )
        try:
            raw = base64.b64decode(final_encoded, validate=True)
        except Exception as exc:  # noqa: BLE001
            raise ProviderStreamProtocolError("image provider returned invalid final base64") from exc
        return self._media(raw, "image/png", "image", config)

    def _decode_response(
        self,
        response: httpx.Response,
        modality: Modality,
        config: ProviderConfig,
    ) -> GeneratedMedia:
        content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if content_type and content_type != "application/json":
            return self._media(response.content, content_type, modality, config)
        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            raise ProviderGenerationError("provider returned neither media nor valid JSON") from exc
        item = (data.get("data") or [data])[0]
        encoded = item.get("b64_json") or item.get("b64") or item.get("base64")
        if encoded:
            try:
                raw = base64.b64decode(encoded, validate=True)
            except Exception as exc:  # noqa: BLE001
                raise ProviderGenerationError("provider returned invalid base64 media") from exc
            declared = item.get("content_type") or self._default_content_type(modality)
            return self._media(raw, declared, modality, config)
        url = item.get("url") or item.get("video_url") or item.get("audio_url")
        if not url:
            raise ProviderGenerationError("provider response did not include media bytes or URL")
        try:
            fetched = httpx.get(url, timeout=settings.ASSET_PROVIDER_TIMEOUT_SECONDS, follow_redirects=True)
            fetched.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderGenerationError(f"provider media download failed: {exc}") from exc
        declared = fetched.headers.get("content-type", "").split(";", 1)[0] or self._default_content_type(modality)
        return self._media(fetched.content, declared, modality, config)

    @staticmethod
    def _default_content_type(modality: Modality) -> str:
        return {"image": "image/png", "audio": "audio/wav", "video": "video/mp4"}[modality]

    @staticmethod
    def _media(raw: bytes, content_type: str, modality: Modality, config: ProviderConfig) -> GeneratedMedia:
        if not raw:
            raise ProviderGenerationError("provider returned empty media")
        if len(raw) > settings.ASSET_PROVIDER_MAX_BYTES:
            raise ProviderGenerationError(
                f"provider media exceeds {settings.ASSET_PROVIDER_MAX_BYTES} bytes"
            )
        extension = {
            "image/svg+xml": ".svg",
            "image/jpeg": ".jpg",
            "image/webp": ".webp",
            "audio/mpeg": ".mp3",
            "audio/ogg": ".ogg",
            "video/webm": ".webm",
        }.get(content_type, {"image": ".png", "audio": ".wav", "video": ".mp4"}[modality])
        return GeneratedMedia(raw, content_type, extension, config.provider, config.model)


class ProviderRouter:
    def __init__(self, adapters: dict[str, ProviderAdapter] | None = None):
        self.adapters: dict[str, ProviderAdapter] = {
            "local": LocalPlaceholderAdapter(),
            "openai-compatible": OpenAICompatibleAdapter(),
            "openai-compat": OpenAICompatibleAdapter(),
        }
        if adapters:
            self.adapters.update(adapters)

    @staticmethod
    def _resolve_prefix(modality: Modality, prefix: str) -> ProviderConfig | None:
        provider = str(getattr(settings, f"{prefix}_PROVIDER", "") or "").strip().lower()
        if not provider:
            return None
        api_key = str(getattr(settings, f"{prefix}_API_KEY", "") or "").strip()
        base_url = str(getattr(settings, f"{prefix}_BASE_URL", "") or "").strip()
        model = str(getattr(settings, f"{prefix}_MODEL", "") or "").strip()
        if provider not in {"local"} and not api_key:
            raise ProviderConfigurationError(f"{prefix}_API_KEY is required for {provider}")
        if provider not in {"local"} and (not base_url or not model):
            raise ProviderConfigurationError(
                f"{prefix}_BASE_URL and {prefix}_MODEL are required for {provider}"
            )
        return ProviderConfig(modality, provider, api_key, base_url, model or provider)

    @classmethod
    def resolve(cls, modality: Modality) -> ProviderConfig | None:
        return cls._resolve_prefix(modality, f"ASSET_{modality.upper()}")

    @classmethod
    def resolve_fallback(cls, modality: Modality) -> ProviderConfig | None:
        """Optional second provider tried after the primary exhausts its retries.

        Configured via ``ASSET_<MODALITY>_FALLBACK_PROVIDER/_API_KEY/_BASE_URL/
        _MODEL``. Unset → no failover (single-provider behavior unchanged).
        """
        return cls._resolve_prefix(modality, f"ASSET_{modality.upper()}_FALLBACK")

    def generate(self, request: MediaRequest, config: ProviderConfig | None = None) -> GeneratedMedia:
        config = config or self.resolve(request.modality)
        if config is None:
            raise ProviderConfigurationError(f"no {request.modality} provider configured")
        adapter = self.adapters.get(config.provider)
        if adapter is None:
            raise ProviderConfigurationError(f"unsupported provider: {config.provider}")
        return adapter.generate(request, config)
