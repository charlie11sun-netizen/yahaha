"""level_layout 契约链:设计坐标 → 背景构图简报 → 像素几何 → 孤儿模块门禁。

2026-07-17 暗影档案(c28261d1)复盘落地的三件事:
1. 图与关卡同源——背景 prompt 按 level_layout 构图,运行时按同一布局建碰撞;
2. 背景亮度底线——prompt 只能劝,生成后确定性检测+提亮才是硬保证;
3. 孤儿模块门禁——集成断链时 21 个已接受作者文件被 Vite 树摇整体丢弃,
   发布了兜底玩法;入口 import 可达性是比死导出更硬的静态信号。
"""
from __future__ import annotations

import io
import json

from app.agents.planning_spec import _coerce_level_layout
from app.agents.repair import _classify_gameplay_failure
from app.agents.validation_nodes import _orphan_author_modules
from app.services.game_assets import (
    _BG_MIN_LUMA,
    _layout_brief,
    _postprocess_background,
    plan_game_assets,
)
from app.services.phaser_projects import (
    _level_layout_px,
    create_modular_phaser_project,
    scaffold_source_paths,
)

_RAW_LAYOUT = {
    "grid": {"cols": 24, "rows": 14},
    "regions": [
        {"id": "entry", "name": "Entry docks", "cells": [0, 0, 5, 13], "kind": "zone"},
        {"id": "office", "name": "Office grid", "cells": [6, 0, 15, 13]},
    ],
    "walls": [[6, 0, 6, 9], [16, 4, 16, 13]],
    "cover": [[9, 5], [10, 8]],
    "paths": [{"id": "patrol_a", "points": [[2, 2], [2, 11], [8, 11]]}],
    "points": [{"id": "exit", "kind": "exit", "at": [23, 7]}],
}


def _design_with_layout() -> dict:
    return {"level_layout": _coerce_level_layout(_RAW_LAYOUT), "palette": {"bg": "#0b1026"}}


# ---------------------------------------------------------------------------
# planning: coercion
# ---------------------------------------------------------------------------

def test_coerce_layout_normalizes_and_injects_spawn():
    layout = _coerce_level_layout(_RAW_LAYOUT)
    assert layout["grid"] == {"cols": 24, "rows": 14}
    assert layout["walls"] == [[6, 0, 6, 9], [16, 4, 16, 13]]
    # 模型没给 spawn 时补一个居中出生点:运行时/作者都依赖它存在。
    kinds = [point["kind"] for point in layout["points"]]
    assert kinds[0] == "spawn" and "exit" in kinds


def test_coerce_layout_clamps_and_drops_malformed():
    layout = _coerce_level_layout(
        {
            "grid": {"cols": 999, "rows": -3},
            "walls": [[-5, 2, 300, 2], "garbage", [1]],
            "cover": [[7, 999], None],
            "paths": [{"id": "p", "points": [[1, 1]]}, {"id": "ok", "points": [[0, 0], [3, 3]]}],
            "points": [{"id": "x", "kind": "exit", "at": "nope"}],
        }
    )
    assert layout["grid"] == {"cols": 48, "rows": 6}  # clamped to bounds
    assert layout["walls"] == [[0, 2, 47, 2]]  # clamped span, garbage dropped
    assert layout["cover"] == [[7, 5]]
    assert [path["id"] for path in layout["paths"]] == ["ok"]  # 单点路径丢弃
    assert all(point["kind"] == "spawn" for point in layout["points"])  # 坏 marker 丢弃,自动补 spawn


def test_coerce_layout_rejects_empty_or_garbage():
    assert _coerce_level_layout(None) is None
    assert _coerce_level_layout("stealth map") is None
    assert _coerce_level_layout({"grid": {"cols": 24, "rows": 14}}) is None


# ---------------------------------------------------------------------------
# assets: layout brief + background prompt + luminance floor
# ---------------------------------------------------------------------------

def test_layout_brief_translates_to_position_words():
    brief = _layout_brief(_design_with_layout())
    assert "Entry docks" in brief and "Office grid" in brief
    assert "wall" in brief and "cover" in brief.lower()
    assert _layout_brief({"level_layout": None}) == ""
    assert _layout_brief({}) == ""


def test_background_prompts_follow_layout_and_forbid_actors():
    state = {
        "game_spec": {"title": "T", "theme": "night facility"},
        "game_design": _design_with_layout(),
    }
    planned = {item.key: item for item in plan_game_assets(state)}
    main_bg = planned["background"].prompt
    # 空舞台约束:画进背景的守卫/视野锥会变成不可交互的假实体。
    assert "no vision cones" in main_bg and "no guards" in main_bg
    # 亮度基调:压暗交给运行时自适应蒙版,不再让图像模型画黑。
    assert "no large near-black areas" in main_bg
    assert "darker and less detailed toward the center" not in main_bg
    # 主图与高压变体共享平面图;background-3 是换区,不套主关卡布局。
    assert "floor plan" in main_bg and "Entry docks" in main_bg
    assert "Entry docks" in planned["background-2"].prompt
    assert "Entry docks" not in planned["background-3"].prompt
    # 高压变体靠彩色警示光而非加黑表达氛围。
    assert "NOT from extra darkness" in planned["background-2"].prompt


def _image_bytes(color: tuple[int, int, int]) -> bytes:
    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", (64, 40), color).save(out, format="PNG")
    return out.getvalue()


def test_postprocess_background_lifts_dark_and_passes_bright():
    dark = _image_bytes((12, 14, 20))  # 暗影档案实测均值 15/255 量级
    content, content_type, extension, before, after = _postprocess_background(dark, "image/png", ".png")
    assert before < _BG_MIN_LUMA and after > before
    assert after >= _BG_MIN_LUMA
    assert content_type == "image/png" and extension == ".png"

    bright = _image_bytes((120, 130, 140))
    content, _, _, before, after = _postprocess_background(bright, "image/webp", ".webp")
    assert content == bright  # 亮图原样直传,字节不动
    assert before == after


# ---------------------------------------------------------------------------
# scaffold: pixel layout + config embedding + adaptive dim
# ---------------------------------------------------------------------------

def test_level_layout_px_scales_cells_to_pixels():
    px = _level_layout_px(_design_with_layout(), 1152, 768)
    cell_w, cell_h = 1152 / 24, 768 / 14
    wall = px["walls"][0]
    assert wall["x"] == round(6 * cell_w, 1) and wall["width"] == round(1 * cell_w, 1)
    first_point = px["paths"][0]["points"][0]
    assert first_point == {"x": round(2.5 * cell_w, 1), "y": round(2.5 * cell_h, 1)}
    assert _level_layout_px({}, 1152, 768) is None


def test_scaffold_embeds_layout_dims_and_level_helper():
    manifest = {
        "assets": [
            {"key": "background", "kind": "image", "path": "assets/background.webp", "luma": 52},
            {"key": "background-2", "kind": "image", "path": "assets/background-2.webp", "luma": 140},
            {"key": "background-3", "kind": "image", "path": "assets/background-3.webp"},
        ]
    }
    files = {
        item["path"]: item.get("content", "")
        for item in create_modular_phaser_project({"title": "T"}, _design_with_layout(), {}, manifest)
    }
    config = files["src/config/gameConfig.ts"]
    parsed = json.loads(config.split("export const gameConfig = ")[1].split(" as GeneratedGameConfig")[0])
    assert parsed["levelLayout"]["walls"], "levelLayout must be embedded in gameConfig"
    # 实测亮度→自适应压暗:暗图轻蒙版,亮图重蒙版,没量过的不进表(运行时用默认)。
    assert parsed["backdropDims"]["background"] < parsed["backdropDims"]["background-2"]
    assert "background-3" not in parsed["backdropDims"]
    assert "src/systems/LevelLayout.ts" in files
    assert "LevelLayout.buildStatics" in files["src/scenes/PlayScene.ts"]
    assert "LevelLayout" in files["src/scenes/PlayScene.ts"]


def test_scaffold_source_paths_matches_generated_project():
    generated = {item["path"] for item in create_modular_phaser_project({}, {})}
    assert scaffold_source_paths() == frozenset(generated)
    assert "src/systems/LevelLayout.ts" in scaffold_source_paths()


# ---------------------------------------------------------------------------
# QA: orphan author modules + repair routing
# ---------------------------------------------------------------------------

def _project_with(extra: dict[str, str]) -> list[dict]:
    files = [dict(item) for item in create_modular_phaser_project({"title": "T"}, {})]
    for path, content in extra.items():
        files.append({"path": path, "content": content})
    return files


def test_orphan_author_modules_flags_unwired_and_accepts_wired():
    assert _orphan_author_modules(create_modular_phaser_project({}, {})) == []

    unwired = _project_with(
        {
            "src/entities/GuardController.ts": "export class GuardController {}",
            "src/content/MissionDefinition.ts": "export const MissionDefinition = {};",
            "src/systems/AlertSystem.ts": "export class AlertSystem {}",
        }
    )
    assert _orphan_author_modules(unwired) == [
        "src/content/MissionDefinition.ts",
        "src/entities/GuardController.ts",
        "src/systems/AlertSystem.ts",
    ]

    wired = _project_with(
        {
            "src/entities/GuardController.ts": 'import { MissionDefinition } from "../content/MissionDefinition";\nexport class GuardController { d = MissionDefinition; }',
            "src/content/MissionDefinition.ts": "export const MissionDefinition = {};",
        }
    )
    for item in wired:
        if item["path"] == "src/scenes/PlayScene.ts":
            item["content"] = 'import { GuardController } from "../entities/GuardController";\nvoid GuardController;\n' + item["content"]
    assert _orphan_author_modules(wired) == []


def test_orphan_author_modules_resolves_barrel_imports():
    project = _project_with(
        {
            "src/presentation/index.ts": 'export { FeedbackRenderer } from "./FeedbackRenderer";',
            "src/presentation/FeedbackRenderer.ts": "export class FeedbackRenderer {}",
        }
    )
    for item in project:
        if item["path"] == "src/scenes/PlayScene.ts":
            item["content"] = 'import { FeedbackRenderer } from "../presentation";\nvoid FeedbackRenderer;\n' + item["content"]
    assert _orphan_author_modules(project) == []


def test_new_wiring_issues_route_to_minimal_patch_repair():
    qa_result = {
        "issues": [
            "authored gameplay modules are never imported by the running game: src/entities/GuardController.ts. Wire these accepted modules into the scene composition",
            "design provides a structured level_layout but gameplay never consumes it: build the level geometry from gameConfig.levelLayout",
            "declared enemy roster never spawned during the sandbox replay: the design lists 3 enemy/boss archetypes",
        ]
    }
    kind, _ = _classify_gameplay_failure(qa_result)
    # 接线级缺陷走最小 patch:作者内容已经存在,整包重生成反而丢内容。
    assert kind == "quality"
