"""background=transparent degradation for gateways that reject the parameter.

The accel/sub2api chatgpt-backend image channel returns
400 "Transparent background is not supported for this model." instead of
ignoring the parameter. Prompts already demand a solid magenta backdrop that
`_postprocess_spritesheet` chroma-keys, so stripping the parameter and
retrying preserves transparency end to end.
"""
from __future__ import annotations

import base64

import httpx
import pytest

from app.core import telemetry
from app.core.config import settings
from app.services import game_assets, provider_router
from app.services.provider_router import (
    GeneratedMedia,
    MediaRequest,
    OpenAICompatibleAdapter,
    ProviderConfig,
    ProviderGenerationError,
)

REJECTION = (
    "image provider request failed: Client error '400 Bad Request' for url "
    "'https://gw.example/v1/images/generations' | body: "
    '{"error":{"code":"invalid_value","message":"Transparent background is not '
    'supported for this model.","param":"tools","type":"image_generation_user_error"}}'
)


@pytest.fixture(autouse=True)
def _reset_transparent_state(monkeypatch):
    monkeypatch.setattr(game_assets, "_transparent_param_unsupported", False)
    monkeypatch.setattr(settings, "ASSET_IMAGE_NATIVE_TRANSPARENCY", "auto")


class _Router:
    def __init__(self, reject_background: bool = True):
        self.requests: list[MediaRequest] = []
        self.reject_background = reject_background

    def generate(self, request: MediaRequest) -> GeneratedMedia:
        self.requests.append(request)
        if self.reject_background and (request.extra or {}).get("background") == "transparent":
            raise ProviderGenerationError(REJECTION)
        return GeneratedMedia(b"png-bytes", "image/png", "png", "openai", "gpt-image-2")


def _sheet_request() -> MediaRequest:
    return MediaRequest(
        modality="image",
        prompt="sheet",
        size="1024x1024",
        extra={"background": "transparent", "quality": "medium"},
    )


def test_auto_mode_strips_background_after_provider_rejection():
    router = _Router()
    logs: list[str] = []
    media = game_assets._generate_with_retry(router, _sheet_request(), logs, "sheet")
    assert media.content == b"png-bytes"
    assert [r.extra for r in router.requests] == [
        {"background": "transparent", "quality": "medium"},
        {"quality": "medium"},
    ]
    assert game_assets._transparent_param_unsupported is True
    assert any("rejected background=transparent" in line for line in logs)


def test_process_memo_pre_strips_background_for_later_assets():
    game_assets._generate_with_retry(_Router(), _sheet_request(), [], "sheet-1")
    router = _Router()
    logs: list[str] = []
    game_assets._generate_with_retry(router, _sheet_request(), logs, "sheet-2")
    assert [r.extra for r in router.requests] == [{"quality": "medium"}]
    assert any("background=transparent omitted" in line for line in logs)


def test_strip_retry_survives_zero_retry_budget(monkeypatch):
    monkeypatch.setattr(settings, "ASSET_PROVIDER_MAX_RETRIES", 0)
    router = _Router()
    media = game_assets._generate_with_retry(router, _sheet_request(), [], "sheet")
    assert media.content == b"png-bytes"
    assert len(router.requests) == 2


def test_never_mode_skips_background_without_provider_error(monkeypatch):
    monkeypatch.setattr(settings, "ASSET_IMAGE_NATIVE_TRANSPARENCY", "never")
    router = _Router()
    game_assets._generate_with_retry(router, _sheet_request(), [], "sheet")
    assert [r.extra for r in router.requests] == [{"quality": "medium"}]


def test_unrelated_errors_strip_only_as_last_resort_without_memo(monkeypatch):
    """持续 5xx 时最后一搏剥参重试(部分网关按参数路由到坏上游),但不写
    进程级记忆——下一张图仍然先带 transparent 参数(2026-07-20 三路守卫)。"""
    monkeypatch.setattr(settings, "ASSET_PROVIDER_MAX_RETRIES", 0)

    class _Fail:
        def __init__(self):
            self.requests: list[MediaRequest] = []

        def generate(self, request: MediaRequest) -> GeneratedMedia:
            self.requests.append(request)
            raise ProviderGenerationError("image provider request failed: 500 upstream broke")

    router = _Fail()
    logs: list[str] = []
    with pytest.raises(ProviderGenerationError):
        game_assets._generate_with_retry(router, _sheet_request(), logs, "sheet")
    assert [(r.extra or {}).get("background") for r in router.requests] == ["transparent", None]
    assert any("last-resort retry without background=transparent" in line for line in logs)
    assert game_assets._transparent_param_unsupported is False


def test_sync_provider_error_includes_response_body(monkeypatch):
    def _post(url, headers=None, json=None, timeout=None):
        request = httpx.Request("POST", url)
        return httpx.Response(
            400,
            request=request,
            json={
                "error": {
                    "code": "invalid_value",
                    "message": "Transparent background is not supported for this model.",
                }
            },
        )

    monkeypatch.setattr(provider_router.httpx, "post", _post)
    adapter = OpenAICompatibleAdapter()
    config = ProviderConfig("image", "openai", "key", "https://gw.example/v1", "gpt-image-2")
    with pytest.raises(ProviderGenerationError) as excinfo:
        adapter.generate(_sheet_request(), config)
    assert "Transparent background is not supported" in str(excinfo.value)


def test_generate_sends_task_scoped_session_header(monkeypatch):
    captured: dict = {}

    def _post(url, headers=None, json=None, timeout=None):
        captured["headers"] = headers
        request = httpx.Request("POST", url)
        return httpx.Response(
            200,
            request=request,
            json={"data": [{"b64_json": base64.b64encode(b"png").decode()}]},
        )

    monkeypatch.setattr(provider_router.httpx, "post", _post)
    telemetry.bind_context(task_id="004fb24c-2460-41c1-8797-b8abf4a112ee")
    try:
        adapter = OpenAICompatibleAdapter()
        config = ProviderConfig("image", "openai", "key", "https://gw.example/v1", "gpt-image-2")
        adapter.generate(MediaRequest(modality="image", prompt="p"), config)
    finally:
        telemetry.bind_context(task_id=None)
    assert captured["headers"]["session_id"] == "gameweave:assets:004fb24c2460"
    assert captured["headers"]["Authorization"] == "Bearer key"


def test_generate_omits_session_header_without_task_context(monkeypatch):
    captured: dict = {}

    def _post(url, headers=None, json=None, timeout=None):
        captured["headers"] = headers
        request = httpx.Request("POST", url)
        return httpx.Response(
            200,
            request=request,
            json={"data": [{"b64_json": base64.b64encode(b"png").decode()}]},
        )

    monkeypatch.setattr(provider_router.httpx, "post", _post)
    telemetry.bind_context(task_id=None)
    adapter = OpenAICompatibleAdapter()
    config = ProviderConfig("image", "openai", "key", "https://gw.example/v1", "gpt-image-2")
    adapter.generate(MediaRequest(modality="image", prompt="p"), config)
    assert "session_id" not in captured["headers"]
