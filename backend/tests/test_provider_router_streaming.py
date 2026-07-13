import base64
from contextlib import contextmanager

import httpx
import pytest

from app.core.config import settings
from app.services import provider_router
from app.services.game_assets import _generate_with_retry
from app.services.provider_router import (
    MediaRequest,
    OpenAICompatibleAdapter,
    ProviderConfig,
    ProviderStreamProtocolError,
)


def _config() -> ProviderConfig:
    return ProviderConfig("image", "openai-compatible", "test-key", "https://images.test/v1", "gpt-image-2")


def _request() -> MediaRequest:
    return MediaRequest("image", "a blue star")


def test_image_stream_uses_completed_event(monkeypatch):
    partial = base64.b64encode(b"partial").decode()
    final = base64.b64encode(b"final-png").decode()
    body = (
        'event: image_generation.partial_image\n'
        f'data: {{"type":"image_generation.partial_image","b64_json":"{partial}","partial_image_index":0}}\n\n'
        'event: image_generation.completed\n'
        f'data: {{"type":"image_generation.completed","b64_json":"{final}"}}\n\n'
    ).encode()
    captured = {}

    @contextmanager
    def fake_stream(method, url, **kwargs):
        captured.update(method=method, url=url, **kwargs)
        yield httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=body,
            request=httpx.Request(method, url),
        )

    monkeypatch.setattr(settings, "ASSET_IMAGE_STREAMING_ENABLED", True)
    monkeypatch.setattr(settings, "ASSET_IMAGE_PARTIAL_IMAGES", 2)
    monkeypatch.setattr(provider_router.httpx, "stream", fake_stream)
    monkeypatch.setattr(provider_router.httpx, "post", lambda *a, **k: pytest.fail("sync fallback used"))

    media = OpenAICompatibleAdapter().generate(_request(), _config())

    assert media.content == b"final-png"
    assert captured["json"]["stream"] is True
    assert captured["json"]["partial_images"] == 2
    assert captured["headers"]["Accept"] == "text/event-stream"


@pytest.mark.parametrize("status", [400, 422])
def test_image_stream_endpoint_error_falls_back_to_sync(monkeypatch, status):
    calls = []

    @contextmanager
    def fake_stream(method, url, **kwargs):
        calls.append("stream")
        yield httpx.Response(
            status,
            request=httpx.Request(method, url),
            json={"error": "unknown field partial_images"},
        )

    def fake_post(url, **kwargs):
        calls.append("sync")
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={"data": [{"b64_json": base64.b64encode(b"sync-png").decode()}]},
        )

    monkeypatch.setattr(settings, "ASSET_IMAGE_STREAMING_ENABLED", True)
    monkeypatch.setattr(provider_router.httpx, "stream", fake_stream)
    monkeypatch.setattr(provider_router.httpx, "post", fake_post)

    media = OpenAICompatibleAdapter().generate(_request(), _config())

    assert media.content == b"sync-png"
    assert calls == ["stream", "sync"]


def test_empty_successful_stream_is_not_retried_or_fallen_back(monkeypatch):
    class EmptyStreamRouter:
        def __init__(self):
            self.calls = 0

        def generate(self, request):
            self.calls += 1
            raise ProviderStreamProtocolError("empty stream")

    router = EmptyStreamRouter()

    with pytest.raises(ProviderStreamProtocolError, match="empty stream"):
        _generate_with_retry(router, _request(), [], "sheet")

    assert router.calls == 1
