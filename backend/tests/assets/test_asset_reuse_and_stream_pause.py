"""第十四轮回归(2026-07-20 三路守卫连锁团灭):

1. 素材阶段重入时逐 key 复用——prompt 未变的图不再回炉重画;
2. gameplay repair 的 balance 兜底不再清空已生成素材;
3. repair agent 基建故障(流中断且零改动)暂停任务而非毁灭性回退;
4. asset_processing 重建清单时保留下游生成条目;
5. 图像请求持续 5xx 时最后一搏剥离 background=transparent;
6. 可选图像兜底提供商在主提供商重试耗尽后接管。
"""
from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw

from app.core.errors import AgentStreamRetryRequired
from app.services import game_assets as game_assets_module
from app.services.game_assets import (
    SHEET_CELL,
    SHEET_GRID,
    SHEET_SIZE,
    _generate_with_retry,
    generate_game_assets,
    stale_planned_keys,
)
from app.services.provider_router import (
    GeneratedMedia,
    MediaRequest,
    ProviderGenerationError,
)


def _png_bytes(img: Image.Image) -> bytes:
    import io

    output = io.BytesIO()
    img.save(output, format="PNG")
    return output.getvalue()


class _CountingRouter:
    """成功路由:画出可通过帧审计的品红底图集/背景,并统计调用。"""

    def __init__(self):
        self.calls = 0
        self.requests: list[MediaRequest] = []
        self._lock = threading.Lock()

    def generate(self, request):
        with self._lock:
            self.calls += 1
            self.requests.append(request)
        img = Image.new("RGB", (SHEET_SIZE, SHEET_SIZE), (255, 0, 255))
        draw = ImageDraw.Draw(img)
        for index in range(SHEET_GRID * SHEET_GRID):
            col, row = index % SHEET_GRID, index // SHEET_GRID
            x0, y0 = col * SHEET_CELL, row * SHEET_CELL
            draw.rectangle([x0 + 72, y0 + 60, x0 + 184, y0 + 232], fill=(30, 30, 30))
        return GeneratedMedia(_png_bytes(img), "image/png", ".png", "stub", "stub-image")


_BASE_STATE = {
    "task_id": "reuse-task",
    "prompt": "arena battle",
    "game_spec": {
        "title": "Reuse Arena",
        "theme": "sci-fi arena",
        "visual_style": "pixel art",
        "genre": "shooter",
    },
    "game_design": {
        "player": {"visual": "blue pilot", "abilities": ["shoot"]},
        "entities": [{"name": "Drone", "role": "enemy", "visual": "grey drone"}],
        "palette": {"bg": "#101820", "primary": "#9ae66e"},
    },
}


@pytest.fixture()
def asset_settings(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "ASSET_GENERATION_ENABLED", True)
    monkeypatch.setattr(settings, "TILEMAP_GENERATION_ENABLED", False)
    monkeypatch.setattr(settings, "ASSET_BACKGROUND_VARIANTS", 1)
    monkeypatch.setattr(game_assets_module, "_transparent_param_unsupported", False)
    return settings


def _generated_state(router=None, state=None):
    router = router or _CountingRouter()
    base = dict(state or _BASE_STATE)
    result = generate_game_assets(base, router=router)
    return {
        **base,
        "generated_assets": result["artifacts"],
        "asset_manifest": {"assets": list(result["manifest_entries"])},
    }, result, router


def test_stale_planned_keys_full_match_and_mismatch(asset_settings):
    state, result, _ = _generated_state()
    assert stale_planned_keys(state) == []

    tampered = {
        **state,
        "asset_manifest": {
            "assets": [
                {**entry, "prompt_hash": "deadbeef"} if entry["key"] == "background" else entry
                for entry in state["asset_manifest"]["assets"]
            ]
        },
    }
    assert stale_planned_keys(tampered) == ["background"]


def test_stale_planned_keys_legacy_manifest_returns_none(asset_settings):
    state, _, _ = _generated_state()
    legacy_entries = [
        {key: value for key, value in entry.items() if key != "prompt_hash"}
        for entry in state["asset_manifest"]["assets"]
    ]
    legacy = {**state, "asset_manifest": {"assets": legacy_entries}}
    assert stale_planned_keys(legacy) is None


def test_generate_game_assets_regenerates_only_stale_keys(asset_settings):
    state, first_result, _ = _generated_state()
    tampered = {
        **state,
        "asset_manifest": {
            "assets": [
                {**entry, "prompt_hash": "deadbeef"} if entry["key"] == "background" else entry
                for entry in state["asset_manifest"]["assets"]
            ]
        },
    }
    router = _CountingRouter()
    result = generate_game_assets(tampered, router=router)

    assert router.calls == 1, "只有 prompt 变化的背景应重生成"
    keys = [entry["key"] for entry in result["manifest_entries"]]
    assert sorted(keys) == sorted(entry["key"] for entry in first_result["manifest_entries"])
    assert len(keys) == len(set(keys)), "复用+重生成不得产生重复条目"
    assert any("reused previously generated" in log for log in result["logs"])
    assert result["asset_request_count"] == 1
    sheet_entry = next(entry for entry in result["manifest_entries"] if entry["key"] == "sheet")
    assert sheet_entry.get("semantic_frames"), "被复用的图集必须保留语义帧映射"


def test_asset_generation_node_incremental_has_no_duplicates(asset_settings):
    from app.agents.assets import asset_generation_node

    state, first_result, _ = _generated_state()
    tampered_entries = [
        {**entry, "prompt_hash": "deadbeef"} if entry["key"] == "background" else entry
        for entry in state["asset_manifest"]["assets"]
    ]
    node_state = {
        **state,
        "asset_manifest": {"assets": tampered_entries},
    }
    router = _CountingRouter()
    import app.services.game_assets as ga

    factory = type(
        "_RouterFactory",
        (),
        {
            "__new__": lambda cls: router,
            "resolve_fallback": staticmethod(lambda modality: None),
        },
    )
    original = ga.ProviderRouter
    ga.ProviderRouter = factory  # type: ignore[assignment]
    try:
        update = asset_generation_node(node_state)
    finally:
        ga.ProviderRouter = original
    keys = [entry["key"] for entry in update["asset_manifest"]["assets"]]
    assert len(keys) == len(set(keys)), "manifest 合并必须替换生成条目而不是追加"
    assert len(update["generated_assets"]) == len(first_result["artifacts"])


def test_asset_generation_node_short_circuits_on_full_match(asset_settings):
    from app.agents.assets import asset_generation_node

    state, _, _ = _generated_state()
    update = asset_generation_node(dict(state))
    assert any("reused" in log for log in update["_logs"])
    assert "generated_assets" not in update, "全量匹配时不应触发重生成"


def test_gameplay_repair_fallback_preserves_hashed_assets(monkeypatch, asset_settings):
    from app.agents import repair as repair_module

    state, _, _ = _generated_state()
    state.update(
        {
            "gameplay_qa_result": {"passed": False, "issues": ["game is unwinnable by design"]},
            "gameplay_repair_attempts": 0,
        }
    )
    monkeypatch.setattr(repair_module.code_agent, "enabled", lambda _state: False)
    update = repair_module.gameplay_repair_node(state)

    assert "generated_assets" not in update, "balance 兜底不得清空已生成素材"
    assert "asset_manifest" not in update
    assert update["generated_files"] == []
    assert any("preserved" in log for log in update["_logs"])


def test_gameplay_repair_fallback_clears_legacy_assets(monkeypatch, asset_settings):
    from app.agents import repair as repair_module

    state, _, _ = _generated_state()
    state["asset_manifest"] = {
        "assets": [
            {key: value for key, value in entry.items() if key != "prompt_hash"}
            for entry in state["asset_manifest"]["assets"]
        ]
    }
    state.update(
        {
            "gameplay_qa_result": {"passed": False, "issues": ["game is unwinnable by design"]},
            "gameplay_repair_attempts": 0,
        }
    )
    monkeypatch.setattr(repair_module.code_agent, "enabled", lambda _state: False)
    update = repair_module.gameplay_repair_node(state)

    assert update["generated_assets"] == [], "无哈希旧清单保持整体重生成语义"
    assert update["asset_manifest"] == {}


def test_gameplay_repair_stream_error_pauses_instead_of_fallback(monkeypatch):
    from app.agents import repair as repair_module

    outcome = SimpleNamespace(
        stop_reason="stream_error",
        changed=[],
        files=[],
        tokens=0,
        turns=1,
        logs=[],
        note="Connection error while streaming",
        checks_ok=False,
    )
    monkeypatch.setattr(repair_module.code_agent, "enabled", lambda _state: True)
    monkeypatch.setattr(repair_module.code_agent, "run_repair", lambda *args, **kwargs: outcome)
    state = {
        "gameplay_qa_result": {
            "passed": False,
            "issues": ["visual review: HUD readability is marginal (2/5)"],
        },
        "generated_files": [{"path": "game.js", "content": "x"}],
        "gameplay_repair_attempts": 0,
    }
    with pytest.raises(AgentStreamRetryRequired):
        repair_module.gameplay_repair_node(state)


def test_asset_processing_carries_generated_entries():
    from app.agents.planning_nodes import asset_processing_node

    generated_entry = {
        "key": "sheet",
        "kind": "spritesheet",
        "path": "assets/sheet.png",
        "prompt_hash": "abc123",
    }
    state = {
        "sprite_demand_manifest": {"demands": [], "contract_hash": None},
        "asset_manifest": {
            "assets": [
                {"id": "u1", "key": "logo.png", "type": "image", "url": "http://x", "source": "uploaded"},
                generated_entry,
            ]
        },
    }
    update = asset_processing_node(state)
    keys = [entry.get("key") for entry in update["asset_manifest"]["assets"]]
    assert "sheet" in keys, "重建清单必须保留下游生成条目"


def test_generate_with_retry_last_resort_strips_transparent(monkeypatch, asset_settings):
    monkeypatch.setattr(asset_settings, "ASSET_PROVIDER_MAX_RETRIES", 1)

    class TransparentPoisonedRouter(_CountingRouter):
        def generate(self, request):
            if str((request.extra or {}).get("background") or "").lower() == "transparent":
                with self._lock:
                    self.calls += 1
                raise ProviderGenerationError(
                    "image provider request failed: Server error '502 Bad Gateway'"
                )
            return super().generate(request)

    router = TransparentPoisonedRouter()
    logs: list[str] = []
    media = _generate_with_retry(
        router,
        MediaRequest(modality="image", prompt="sheet", extra={"background": "transparent"}),
        logs,
        "sheet",
    )
    assert media.content_type == "image/png"
    assert any("last-resort retry without background=transparent" in log for log in logs)


def test_generate_with_retry_uses_fallback_provider(monkeypatch, asset_settings):
    monkeypatch.setattr(asset_settings, "ASSET_PROVIDER_MAX_RETRIES", 0)
    monkeypatch.setattr(asset_settings, "ASSET_IMAGE_FALLBACK_PROVIDER", "openai-compatible")
    monkeypatch.setattr(asset_settings, "ASSET_IMAGE_FALLBACK_API_KEY", "key")
    monkeypatch.setattr(asset_settings, "ASSET_IMAGE_FALLBACK_BASE_URL", "https://fallback.example/v1")
    monkeypatch.setattr(asset_settings, "ASSET_IMAGE_FALLBACK_MODEL", "img-model")

    class PrimaryDownRouter(_CountingRouter):
        def generate(self, request, config=None):
            if config is None:
                raise ProviderGenerationError("image provider request failed: 502")
            assert config.base_url == "https://fallback.example/v1"
            return super().generate(request)

    router = PrimaryDownRouter()
    logs: list[str] = []
    media = _generate_with_retry(
        router,
        MediaRequest(modality="image", prompt="background"),
        logs,
        "background",
    )
    assert media.content_type == "image/png"
    assert any("failing over" in log for log in logs)
