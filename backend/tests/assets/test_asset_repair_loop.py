"""第十二轮(2026-07-19)修复循环结构测试.

覆盖:pass 判决锁定(只复审重画格)、失败集不收缩即止损、修复图像预算、
coverage 达标带伤放行/低于底线暂停、单格失败不再整体暂停、身份锚定提示词、
UI 覆盖物剥离、layout 评审失败退回固定网格切割。
"""
import io
import threading

import pytest
from PIL import Image, ImageDraw

from app.core.config import settings
from app.services import game_assets
from app.services.game_assets import (
    SHEET_CELL,
    SHEET_GRID,
    SHEET_SIZE,
    AssetGenerationRetryRequired,
    PlannedAsset,
    SheetCell,
    _cell_demand,
    _merge_semantic_review_into_audit,
    _regeneration_plan_audit,
    _repair_failed_sheet_frames,
    _sheet_regen_prompt,
    generate_game_assets,
)
from app.services.provider_router import GeneratedMedia, ProviderGenerationError
from app.services.sprite_pipeline import (
    BatchSpec,
    SpriteDemandManifest,
    build_cell_regeneration_specs,
    strip_ui_overlay_demands,
)


def _png(img: Image.Image) -> bytes:
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


_CELLS = (
    SheetCell("hero_idle", "brown-haired hero standing idle", semantic_id="hero.idle"),
    SheetCell("hero_move", "same hero running", semantic_id="hero.move"),
    SheetCell("orc_idle", "green orc warrior", semantic_id="orc.idle"),
    SheetCell("orc_attack", "same orc swinging axe", semantic_id="orc.attack"),
)
_IDS = tuple(_cell_demand(cell).semantic_id for cell in _CELLS)


def _item() -> PlannedAsset:
    return PlannedAsset("sheet", "image", "prompt", sheet_cells=_CELLS)


def _manifest() -> SpriteDemandManifest:
    return SpriteDemandManifest(tuple(_cell_demand(cell) for cell in _CELLS))


def _batch() -> BatchSpec:
    return BatchSpec("sheet", "sheet", _IDS, SHEET_GRID, SHEET_GRID)


def _sheet_content() -> bytes:
    return _png(Image.new("RGBA", (SHEET_SIZE, SHEET_SIZE), (0, 0, 0, 0)))


def _pixel_audit(content: bytes, cells) -> dict:
    frames = [
        {
            "semantic_id": _cell_demand(cell).semantic_id,
            "frame_index": index,
            "required": True,
            "passed": True,
            "checks": {},
            "failed_checks": [],
        }
        for index, cell in enumerate(cells)
    ]
    return {
        "schema_version": "frame-audit/v1",
        "dimensions": [SHEET_SIZE, SHEET_SIZE],
        "frame_count": len(frames),
        "frames": frames,
        "failed_frame_ids": [],
        "required_asset_coverage": 1.0,
        "unused_required_frame": 0,
        "passed": True,
    }


def _review(verdicts: dict[str, str], ids=None, checks: dict[str, list] | None = None) -> dict:
    ids = list(ids if ids is not None else _IDS)
    checks = checks or {}
    frames = []
    for index, semantic_id in enumerate(ids):
        verdict = verdicts.get(semantic_id, "pass")
        frames.append(
            {
                "semantic_id": semantic_id,
                "frame_index": index,
                "verdict": verdict,
                "observed_category": f"observed {semantic_id}",
                "confidence": 0.97,
                "failed_checks": checks.get(semantic_id, ["wrong_state"] if verdict != "pass" else []),
                "repair_prompt": "",
            }
        )
    failed = [f["semantic_id"] for f in frames if f["verdict"] == "fail"]
    uncertain = [f["semantic_id"] for f in frames if f["verdict"] == "uncertain"]
    return {
        "schema_version": "asset-semantic-review/v2",
        "enabled": True,
        "status": "failed" if failed or uncertain else "passed",
        "passed": not failed and not uncertain,
        "frames": frames,
        "failed_frame_ids": failed,
        "uncertain_frame_ids": uncertain,
        "recheck_used": False,
    }


class _RegenRouter:
    """整表重掷路由:每次调用返回一张 1024 画布(计数线程安全)。"""

    def __init__(self):
        self.calls = 0
        self._lock = threading.Lock()

    def generate(self, request):
        with self._lock:
            self.calls += 1
        img = Image.new("RGBA", (SHEET_SIZE, SHEET_SIZE), (0, 0, 0, 0))
        ImageDraw.Draw(img).rectangle([60, 60, 200, 200], fill=(40, 40, 40, 255))
        return GeneratedMedia(_png(img), "image/png", ".png", "stub", "stub-image")


class _FailingRouter:
    def __init__(self):
        self.calls = 0
        self._lock = threading.Lock()

    def generate(self, request):
        with self._lock:
            self.calls += 1
        raise ProviderGenerationError("image provider request failed: gateway timeout")


def _repair_env(monkeypatch, *, floor=0.7, budget=8, rounds=2):
    monkeypatch.setattr(settings, "ASSET_SEMANTIC_REVIEW_ENABLED", True)
    monkeypatch.setattr(settings, "ASSET_SEMANTIC_REVIEW_MAX_RETRIES", 0)
    monkeypatch.setattr(settings, "ASSET_FRAME_AUDIT_MAX_RETRIES", rounds)
    monkeypatch.setattr(settings, "ASSET_REPAIR_MAX_IMAGE_CALLS", budget)
    monkeypatch.setattr(settings, "ASSET_RELEASE_COVERAGE_FLOOR", floor)
    monkeypatch.setattr(settings, "ASSET_GENERATION_CONCURRENCY", 1)
    monkeypatch.setattr(settings, "ASSET_PROVIDER_MAX_RETRIES", 0)
    monkeypatch.setattr(game_assets, "_audit_sheet_frames", _pixel_audit)
    monkeypatch.setattr(
        game_assets,
        "_slice_sheet_canvas",
        lambda raw, content_type, item, manifest, batch, logs: (
            raw,
            {"enabled": False},
            {"resegmented": False},
        ),
    )


def _scripted_review(monkeypatch, script: list[dict[str, str]], captured: list):
    def fake_review(content, manifest, batch, *, attempt=1, target_semantic_ids=None, accepted_context=None):
        targets = tuple(target_semantic_ids or ())
        captured.append({"targets": targets, "accepted": dict(accepted_context or {})})
        verdicts = script.pop(0)
        return _review(verdicts, ids=targets or _IDS)

    monkeypatch.setattr(game_assets, "review_spritesheet", fake_review)


def _initial_state(fail: dict[str, list]) -> tuple[dict, dict]:
    review = _review({sid: "fail" for sid in fail}, checks=fail)
    audit = _merge_semantic_review_into_audit(_pixel_audit(b"", _CELLS), review)
    return audit, review


def test_repair_regenerates_full_sheet_and_swaps_best_cells(monkeypatch):
    _repair_env(monkeypatch)
    captured: list = []
    # 第 1 次评审=候选表全量(全过);第 2 次=换入格跨表校验(过)
    _scripted_review(monkeypatch, [{}, {}], captured)
    audit, review = _initial_state({"hero.move": ["duplicate_cell"]})
    router = _RegenRouter()
    logs: list[str] = []

    content, out_audit, out_review = _repair_failed_sheet_frames(
        _sheet_content(), _item(), audit, review, _batch(), _manifest(), {}, router, logs
    )

    assert out_audit["passed"] is True
    assert router.calls == 1, "整表重掷每轮只允许 1 次图像调用"
    assert captured[0]["targets"] == (), "候选表做全量评审"
    assert captured[1]["targets"] == ("hero.move",), "跨表校验只审换入格"
    assert set(captured[1]["accepted"]) == {"hero.idle", "orc.idle", "orc.attack"}
    assert not out_audit.get("released_with_warnings")


def test_repair_stops_when_candidate_improves_nothing_then_releases(monkeypatch):
    _repair_env(monkeypatch, floor=0.7, rounds=2)
    # 候选表里该格仍失败 → 没有可换入的格 → 立即止损,不烧后续轮
    _scripted_review(monkeypatch, [{"hero.move": "fail"}], [])
    audit, review = _initial_state({"hero.move": ["duplicate_cell"]})
    router = _RegenRouter()
    logs: list[str] = []

    content, out_audit, out_review = _repair_failed_sheet_frames(
        _sheet_content(), _item(), audit, review, _batch(), _manifest(), {}, router, logs
    )

    assert router.calls == 1, "止损后不得再烧图像调用"
    assert out_audit["released_with_warnings"] is True
    assert out_audit["failed_frame_ids"] == ["hero.move"]
    assert any("improved no failed cell" in log for log in logs)
    assert any("released with 1 imperfect required frame" in log for log in logs)


def test_repair_raises_below_coverage_floor(monkeypatch):
    _repair_env(monkeypatch, floor=0.9, rounds=2)
    _scripted_review(monkeypatch, [{"hero.move": "fail"}], [])
    audit, review = _initial_state({"hero.move": ["duplicate_cell"]})

    with pytest.raises(AssetGenerationRetryRequired, match="below the release floor"):
        _repair_failed_sheet_frames(
            _sheet_content(), _item(), audit, review, _batch(), _manifest(), {}, _RegenRouter(), []
        )


def test_repair_budget_caps_sheet_regens(monkeypatch):
    _repair_env(monkeypatch, floor=0.7, budget=1, rounds=3)
    captured: list = []
    # 轮 1:候选表修好 hero.move、orc.idle 仍失败;换入格校验过。
    _scripted_review(monkeypatch, [{"orc.idle": "fail"}, {}], captured)
    audit, review = _initial_state(
        {"hero.move": ["duplicate_cell"], "orc.idle": ["wrong_state"]}
    )
    router = _RegenRouter()
    logs: list[str] = []

    content, out_audit, out_review = _repair_failed_sheet_frames(
        _sheet_content(), _item(), audit, review, _batch(), _manifest(), {}, router, logs
    )

    assert router.calls == 1, "预算=1 只允许一次整表重掷"
    assert captured[1]["targets"] == ("hero.move",)
    assert out_audit["released_with_warnings"] is True
    assert out_audit["failed_frame_ids"] == ["orc.idle"]
    assert any("budget exhausted" in log for log in logs)


def test_regen_provider_failure_leaves_cells_for_release(monkeypatch):
    _repair_env(monkeypatch, floor=0.7)
    _scripted_review(monkeypatch, [], [])  # 重掷失败 → 不会触发任何评审
    audit, review = _initial_state({"hero.move": ["duplicate_cell"]})
    router = _FailingRouter()
    logs: list[str] = []

    content, out_audit, out_review = _repair_failed_sheet_frames(
        _sheet_content(), _item(), audit, review, _batch(), _manifest(), {}, router, logs
    )

    assert out_audit["released_with_warnings"] is True
    assert any("sheet regeneration failed" in log for log in logs)


def test_swapped_cell_reverts_when_cross_sheet_check_fails(monkeypatch):
    _repair_env(monkeypatch, floor=0.7, rounds=2)
    # 候选表全过,但换入格的跨表身份校验判 fail → 回退换入,保持旧表
    _scripted_review(monkeypatch, [{}, {"hero.move": "fail"}], [])
    audit, review = _initial_state({"hero.move": ["duplicate_cell"]})
    router = _RegenRouter()
    logs: list[str] = []

    content, out_audit, out_review = _repair_failed_sheet_frames(
        _sheet_content(), _item(), audit, review, _batch(), _manifest(), {}, router, logs
    )

    assert router.calls == 1
    assert out_audit["released_with_warnings"] is True
    assert out_audit["failed_frame_ids"] == ["hero.move"]
    assert any("reverted after cross-sheet check" in log for log in logs)
    assert any("no swapped cell survived" in log for log in logs)


def test_merge_treats_uncertain_as_soft_not_failure():
    review = _review({"orc.attack": "uncertain"})
    audit = _merge_semantic_review_into_audit(_pixel_audit(b"", _CELLS), review)

    assert audit["passed"] is True
    assert audit["failed_frame_ids"] == []
    assert audit["soft_frame_ids"] == ["orc.attack"]
    assert audit["required_asset_coverage"] == 1.0


def test_regeneration_plan_covers_soft_cells():
    review = _review({"orc.attack": "uncertain"})
    audit = _merge_semantic_review_into_audit(_pixel_audit(b"", _CELLS), review)
    specs = build_cell_regeneration_specs(_regeneration_plan_audit(audit), _batch())

    assert [spec.semantic_id for spec in specs] == ["orc.attack"]
    assert "orc.attack" not in specs[0].reference_semantic_ids


def test_sheet_regen_prompt_carries_feedback_and_strips_ui():
    review = _review({"hero.move": "fail"}, checks={"hero.move": ["duplicate_cell"]})
    for frame in review["frames"]:
        if frame["semantic_id"] == "hero.move":
            frame["repair_prompt"] = "redraw running pose, add health bar above head"
    audit = _merge_semantic_review_into_audit(_pixel_audit(b"", _CELLS), review)
    prompt = _sheet_regen_prompt(_item(), audit, review)

    assert "CORRECTION PASS" in prompt
    assert "hero.move" in prompt and "duplicate_cell" in prompt
    assert "redraw running pose" in prompt
    assert "health bar" not in prompt
    assert "FULL sheet" in prompt


def test_strip_ui_overlay_demands():
    assert (
        strip_ui_overlay_demands("armored knight with shield, health bar above head")
        == "armored knight with shield"
    )
    assert strip_ui_overlay_demands("蓝甲骑士挥剑,头顶血条,脚下阴影") == "蓝甲骑士挥剑,脚下阴影"
    assert strip_ui_overlay_demands("plain slime enemy") == "plain slime enemy"
    assert strip_ui_overlay_demands("floating damage number") == ""


def test_audit_frame_ignores_minor_effect_fragments():
    """像素防线取证(2026-07-19):挥砍特效/粒子碎片不是第二个物体。"""

    from app.services.sprite_pipeline import SpriteDemand, audit_frame

    img = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rectangle([100, 120, 160, 254], fill=(40, 40, 40, 255))  # 主体剪影
    draw.rectangle([70, 100, 84, 110], fill=(200, 60, 40, 255))  # 特效碎片 1
    draw.rectangle([180, 90, 192, 102], fill=(200, 60, 40, 255))  # 特效碎片 2
    demand = SpriteDemand(
        semantic_id="hero.action",
        frame_id="hero_action",
        object_name="hero",
        state="action",
        consumer_refs=("x",),
    )
    result = audit_frame(img, demand)

    assert result["detected_object_count"] == 1
    assert result["checks"]["single_expected_object"] is True


def test_audit_frame_still_fails_two_comparable_silhouettes():
    from app.services.sprite_pipeline import SpriteDemand, audit_frame

    img = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rectangle([30, 120, 110, 250], fill=(40, 40, 40, 255))
    draw.rectangle([150, 120, 230, 250], fill=(60, 60, 90, 255))
    demand = SpriteDemand(
        semantic_id="town.block",
        frame_id="town_block",
        object_name="town",
        state="block",
        consumer_refs=("x",),
    )
    result = audit_frame(img, demand)

    assert result["detected_object_count"] == 2
    assert result["checks"]["single_expected_object"] is False


def test_semantic_pass_overrides_pixel_object_count_false_positive():
    pixel = _pixel_audit(b"", _CELLS)
    frame = pixel["frames"][1]
    frame["passed"] = False
    frame["failed_checks"] = ["single_expected_object"]
    frame["checks"] = {"single_expected_object": False}
    pixel["failed_frame_ids"] = [frame["semantic_id"]]
    pixel["passed"] = False

    audit = _merge_semantic_review_into_audit(pixel, _review({}))

    assert audit["passed"] is True
    assert audit["failed_frame_ids"] == []
    merged = audit["frames"][1]
    assert merged["checks"]["single_expected_object"] is True
    assert merged["checks"]["single_expected_object_overridden"] is True


def test_semantic_pass_does_not_override_geometry_failures():
    pixel = _pixel_audit(b"", _CELLS)
    frame = pixel["frames"][1]
    frame["passed"] = False
    frame["failed_checks"] = ["cell_boundary"]
    frame["checks"] = {"cell_boundary": False}
    pixel["failed_frame_ids"] = [frame["semantic_id"]]
    pixel["passed"] = False

    audit = _merge_semantic_review_into_audit(pixel, _review({}))

    assert audit["passed"] is False
    assert audit["failed_frame_ids"] == [frame["semantic_id"]]


def test_reuse_manifest_gate_matches_release_semantics(monkeypatch):
    """续跑/复用门禁不得推翻主流程的带伤放行与固定网格兜底决定。"""

    from app.agents.assets import _manifest_gate

    monkeypatch.setattr(settings, "ASSET_SEMANTIC_REVIEW_ENABLED", True)
    monkeypatch.setattr(settings, "ASSET_RELEASE_COVERAGE_FLOOR", 0.8)
    released_entry = {
        "kind": "spritesheet",
        "key": "sheet",
        "frame_audit": {
            "passed": False,
            "released_with_warnings": True,
            "required_asset_coverage": 0.9375,
            "failed_frame_ids": ["hero.move"],
        },
        "semantic_review": {"enabled": True, "passed": False, "failed_frame_ids": ["hero.move"]},
        "layout_review": {"enabled": True, "passed": False, "status": "unavailable"},
        "layout_repack": {"resegmented": False, "fallback": "fixed_grid"},
    }
    assert _manifest_gate({"asset_manifest": {"assets": [released_entry]}})["status"] == "passed"

    below_floor = {
        **released_entry,
        "frame_audit": {**released_entry["frame_audit"], "required_asset_coverage": 0.5},
    }
    assert (
        _manifest_gate({"asset_manifest": {"assets": [below_floor]}})["status"]
        == "manual_recovery_required"
    )

    unreleased_failure = {
        **released_entry,
        "frame_audit": {"passed": False, "required_asset_coverage": 0.9},
    }
    assert (
        _manifest_gate({"asset_manifest": {"assets": [unreleased_failure]}})["status"]
        == "manual_recovery_required"
    )

    hybrid_resegmented = {
        **released_entry,
        "layout_repack": {"resegmented": True, "hybrid_cell_ids": ["hero.move"]},
    }
    assert _manifest_gate({"asset_manifest": {"assets": [hybrid_resegmented]}})["status"] == "passed"

    no_layout_evidence = {
        **released_entry,
        "layout_review": {},
        "layout_repack": {},
    }
    assert (
        _manifest_gate({"asset_manifest": {"assets": [no_layout_evidence]}})["status"]
        == "manual_recovery_required"
    )


class _MagentaSheetRouter:
    """1024 品红底+每格深色方块:与既有 generate 测试同款可切割画布。"""

    def generate(self, request):
        img = Image.new("RGB", (SHEET_SIZE, SHEET_SIZE), (255, 0, 255))
        draw = ImageDraw.Draw(img)
        for index in range(SHEET_GRID * SHEET_GRID):
            col, row = index % SHEET_GRID, index // SHEET_GRID
            x0, y0 = col * SHEET_CELL, row * SHEET_CELL
            draw.rectangle([x0 + 72, y0 + 60, x0 + 184, y0 + 232], fill=(30, 30, 30))
        return GeneratedMedia(_png(img), "image/png", ".png", "stub", "stub-image")


_FLOW_STATE = {
    "prompt": "top-down shooter",
    "game_spec": {"title": "T", "theme": "military", "genre": "shooter", "visual_style": "pixel"},
    "game_design": {
        "player": {"visual": "soldier with rifle", "abilities": ["shoot"]},
        "entities": [{"name": "Grunt", "role": "enemy", "visual": "rifleman", "behavior": "advances"}],
        "palette": {"bg": "#101820"},
    },
}


def _all_pass_review(content, manifest, batch, *, attempt=1, target_semantic_ids=None, accepted_context=None):
    manifest = (
        manifest
        if isinstance(manifest, SpriteDemandManifest)
        else SpriteDemandManifest.from_dict(manifest)
    )
    ids = [demand.semantic_id for demand in manifest.demands]
    return _review({}, ids=ids)


def test_layout_review_unavailable_falls_back_to_fixed_grid(monkeypatch):
    monkeypatch.setattr(settings, "ASSET_GENERATION_ENABLED", True)
    monkeypatch.setattr(settings, "TILEMAP_GENERATION_ENABLED", False)
    monkeypatch.setattr(settings, "ASSET_SEMANTIC_REVIEW_ENABLED", True)
    monkeypatch.setattr(settings, "ASSET_SEMANTIC_REVIEW_MAX_RETRIES", 0)

    from app.services.asset_semantic_review import AssetSemanticReviewError

    def dead_layout(content, manifest, batch, *, attempt=1):
        raise AssetSemanticReviewError("sheet: layout review unavailable: gateway down")

    monkeypatch.setattr(game_assets, "review_spritesheet_layout", dead_layout)
    monkeypatch.setattr(game_assets, "review_spritesheet", _all_pass_review)

    result = generate_game_assets(dict(_FLOW_STATE), router=_MagentaSheetRouter())

    keys = {entry["key"] for entry in result["manifest_entries"]}
    assert "sheet" in keys, "layout 评审不可用不再暂停,固定网格兜底后照常发布"
    assert any("falling back to fixed-grid slicing" in log for log in result["logs"])
    sheet_entry = next(e for e in result["manifest_entries"] if e["key"] == "sheet")
    assert sheet_entry["postprocess_checks"]["layout_review"]["resegmented"] is False


def test_partial_layout_mapping_uses_hybrid_resegmentation(monkeypatch):
    """第二跑取证(2026-07-20):部分映射不可整表丢弃,未映射格才走网格矩形。"""

    monkeypatch.setattr(settings, "ASSET_GENERATION_ENABLED", True)
    monkeypatch.setattr(settings, "TILEMAP_GENERATION_ENABLED", False)
    monkeypatch.setattr(settings, "ASSET_SEMANTIC_REVIEW_ENABLED", True)
    monkeypatch.setattr(settings, "ASSET_SEMANTIC_REVIEW_MAX_RETRIES", 0)

    uncertain_holder: dict = {}

    def partial_layout(content, manifest, batch, *, attempt=1):
        manifest = (
            manifest
            if isinstance(manifest, SpriteDemandManifest)
            else SpriteDemandManifest.from_dict(manifest)
        )
        frames = []
        for index, demand in enumerate(manifest.demands):
            col, row = index % 4, index // 4
            frame = {
                "semantic_id": demand.semantic_id,
                "frame_index": index,
                "target_frame_index": index,
                "source_frame_index": index,
                "source_bbox": [col / 4, row / 4, (col + 1) / 4, (row + 1) / 4],
                "verdict": "pass",
                "observed_category": "ok",
                "confidence": 0.97,
                "failed_checks": [],
                "repair_prompt": "",
            }
            if index == 2:
                frame.update(verdict="uncertain", source_bbox=None, failed_checks=["layout_uncertain"])
                uncertain_holder["id"] = demand.semantic_id
            frames.append(frame)
        uncertain_ids = [f["semantic_id"] for f in frames if f["verdict"] != "pass"]
        return {
            "schema_version": "asset-layout-review/v1",
            "enabled": True,
            "status": "failed",
            "passed": False,
            "frames": frames,
            "failed_frame_ids": [],
            "uncertain_frame_ids": uncertain_ids,
            "duplicate_mapping_ids": [],
            "mapping_complete": False,
        }

    monkeypatch.setattr(game_assets, "review_spritesheet_layout", partial_layout)
    monkeypatch.setattr(game_assets, "review_spritesheet", _all_pass_review)

    result = generate_game_assets(dict(_FLOW_STATE), router=_MagentaSheetRouter())

    keys = {entry["key"] for entry in result["manifest_entries"]}
    assert "sheet" in keys
    assert any("hybrid re-segmentation" in log for log in result["logs"])
    sheet_entry = next(e for e in result["manifest_entries"] if e["key"] == "sheet")
    checks = sheet_entry["postprocess_checks"]
    assert checks["layout_review"]["resegmented"] is True
    repack = sheet_entry["layout_repack"]
    assert repack["hybrid_cell_ids"] == [uncertain_holder["id"]]
    hybrid_frames = [f for f in repack["frames"] if f.get("hybrid_grid_fill")]
    assert [f["semantic_id"] for f in hybrid_frames] == [uncertain_holder["id"]]
