"""OpenGame-inspired modular Phaser/Vite/TypeScript project scaffolding.

The scaffold is intentionally a NEUTRAL STAGE plus quality infrastructure, not a
finished game: scene flow (Boot -> Title -> Play -> GameOver), typed config with
a per-game palette, a Juice system (flash / shake / hit-stop / particles /
floating text), and an Sfx system (WebAudio oscillator presets). PlayScene ships
a small placeholder loop (marked GW_PLACEHOLDER_GAMEPLAY) that demonstrates the
quality kit and MUST be replaced by the authoring agent with the designed game.
Keeping gameplay out of the scaffold is deliberate: a finished mother-game made
every generated title feel like a reskin of the same collect-and-dodge arena.
"""
from __future__ import annotations

import hashlib
import json
import re
from functools import lru_cache
from html import escape

from app.services.artifacts import text_artifact
from app.services.phaser_scaffold_templates import (
    AREA_HINT_TS,
    BACKDROP_TS,
    BOOT_SCENE_TS,
    BOUNDS_TS,
    COLORS_TS,
    GAME_CONFIG_TS,
    GAME_OVER_SCENE_TS,
    GAME_STATE_TS,
    GAME_WEAVE_BRIDGE_TS,
    HUD_TS,
    INDEX_HTML,
    INPUT_ROUTER_TS,
    JUICE_TS,
    LEVEL_LAYOUT_TS,
    MAIN_TS,
    PLAYER_TS,
    PLAY_SCENE_TS,
    PROBE_TS,
    SFX_TS,
    STYLES_CSS,
    TITLE_SCENE_TS,
)

_HEX_RE = re.compile(r"^#?[0-9a-fA-F]{6}$")

# Rotating fallback palettes so games without a designed palette still differ
# visually from each other (picked deterministically from title+theme).
_PALETTES: list[dict[str, str]] = [
    {"bg": "#0b1026", "surface": "#141c33", "primary": "#67e8f9", "accent": "#f0abfc", "danger": "#fb7185"},
    {"bg": "#1f1147", "surface": "#2d1b5e", "primary": "#fbbf24", "accent": "#fb923c", "danger": "#f43f5e"},
    {"bg": "#051622", "surface": "#0a2735", "primary": "#34d399", "accent": "#38bdf8", "danger": "#f87171"},
    {"bg": "#0c1f17", "surface": "#16302a", "primary": "#a3e635", "accent": "#4ade80", "danger": "#fb7185"},
    {"bg": "#2a1033", "surface": "#3b1a47", "primary": "#f9a8d4", "accent": "#fde047", "danger": "#f87171"},
    {"bg": "#0a0f0a", "surface": "#121a12", "primary": "#4ade80", "accent": "#a3e635", "danger": "#f87171"},
    {"bg": "#1a0b0b", "surface": "#2a1212", "primary": "#fb923c", "accent": "#fbbf24", "danger": "#ef4444"},
    {"bg": "#0b1420", "surface": "#14212f", "primary": "#e0f2fe", "accent": "#7dd3fc", "danger": "#fda4af"},
    {"bg": "#140f2b", "surface": "#1e1745", "primary": "#a78bfa", "accent": "#f0abfc", "danger": "#fb7185"},
    {"bg": "#1c1410", "surface": "#2b2018", "primary": "#fcd34d", "accent": "#f97316", "danger": "#ef4444"},
]

_PALETTE_KEYS = ("bg", "surface", "primary", "accent", "danger")


def _number(value, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(float(value))
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _clean_hex(value) -> str | None:
    text = str(value or "").strip()
    if not _HEX_RE.match(text):
        return None
    return "#" + text.lstrip("#").lower()


def _palette_for(spec: dict, design: dict) -> dict[str, str]:
    seed = f"{spec.get('title') or ''}|{spec.get('theme') or ''}"
    index = int(hashlib.sha256(seed.encode("utf-8")).hexdigest(), 16) % len(_PALETTES)
    palette = dict(_PALETTES[index])
    raw = design.get("palette") if isinstance(design, dict) else None
    if isinstance(raw, dict):
        for key in _PALETTE_KEYS:
            clean = _clean_hex(raw.get(key))
            if clean:
                palette[key] = clean
    elif isinstance(raw, list):
        for key, value in zip(("bg", "primary", "accent", "danger", "surface"), raw):
            clean = _clean_hex(value)
            if clean:
                palette[key] = clean
    return palette


def _free_params(balance: dict | None, design: dict | None) -> dict[str, float]:
    """Flatten numeric tuning values into a free-form params map.

    The old scaffold hardcoded dodge-collect fields (enemySpeed/spawnMs...) into
    the config type, which nudged every game back toward the same archetype.
    Numbers now travel untyped; gameplay code decides what they mean.
    """
    params: dict[str, float] = {}
    for source in ((balance or {}), (design or {}).get("balance") or {}):
        if not isinstance(source, dict):
            continue
        for key, value in source.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            name = str(key)[:48]
            if name:
                params[name] = float(value)
    return params


def _asset_catalog(
    asset_manifest: dict | None,
) -> tuple[list[dict], dict, list[dict], dict | None, dict[str, float], dict]:
    entries: list[dict] = []
    image_keys: list[str] = []
    backgrounds: list[str] = []
    sheets: list[dict] = []
    tilemap: dict | None = None
    backdrop_dims: dict[str, float] = {}
    sprite_demand_manifest = dict((asset_manifest or {}).get("sprite_demand_manifest") or {})
    for raw in (asset_manifest or {}).get("assets") or []:
        if not isinstance(raw, dict):
            continue
        key = str(raw.get("key") or "").strip()
        path = str(raw.get("path") or "").strip().lstrip("/")
        kind = str(raw.get("kind") or "image").strip().lower()
        if not key or not path or "://" in path or ".." in path.split("/"):
            continue
        if kind not in {"image", "spritesheet", "audio", "video", "tilemap"}:
            continue
        entry: dict = {"key": key, "path": path, "kind": kind}
        if kind == "spritesheet":
            frame_w = _number(raw.get("frame_width"), 256, 8, 1024)
            frame_h = _number(raw.get("frame_height"), 256, 8, 1024)
            entry["frameWidth"] = frame_w
            entry["frameHeight"] = frame_h
            frames = raw.get("frames")
            if isinstance(frames, dict) and frames:
                # 设计实体多时图集溢出为多页(sheet, sheet-2...):全部收集,
                # gameplay 代码经 sheetFrame() 跨页找帧。
                raw_animations = raw.get("animations")
                raw_meta = raw.get("frame_meta")
                raw_families = raw.get("tile_families")
                sheets.append(
                    {
                        "key": key,
                        "frameWidth": frame_w,
                        "frameHeight": frame_h,
                        "frames": {
                            str(name)[:64]: int(index)
                            for name, index in frames.items()
                            if isinstance(index, (int, float)) and not isinstance(index, bool)
                        },
                        # 多帧角色的帧组(玩家姿势集、敌人 idle+攻击、Boss 特技、
                        # 道具激活态):同组帧保证在同一张图上,可直接建 Phaser 动画。
                        "animations": {
                            str(base)[:64]: [str(name)[:64] for name in names if isinstance(name, str)]
                            for base, names in (raw_animations.items() if isinstance(raw_animations, dict) else ())
                            if isinstance(names, (list, tuple)) and names
                        },
                        # 帧语义(素材规划期的格描述):作者绑定实体↔帧的唯一依据。
                        # 帧名(entity_3)不携带含义,靠顺序猜会整局换皮(2026-07-17)。
                        "frameMeta": {
                            str(name)[:64]: str(text)[:120]
                            for name, text in (raw_meta.items() if isinstance(raw_meta, dict) else ())
                            if isinstance(text, str) and text
                        },
                        "semanticFrames": {
                            str(semantic_id)[:96]: dict(value)
                            for semantic_id, value in (raw.get("semantic_frames") or {}).items()
                            if isinstance(value, dict)
                        },
                        "frameAudit": dict(raw.get("frame_audit") or {}),
                        "frameIds": {
                            str(name)[:64]: int(index)
                            for name, index in (raw.get("frame_ids") or {}).items()
                            if isinstance(index, (int, float)) and not isinstance(index, bool)
                        },
                        "frameSemantics": {
                            str(name)[:64]: str(semantic_id)[:96]
                            for name, semantic_id in (raw.get("frame_semantics") or {}).items()
                            if isinstance(semantic_id, str)
                        },
                        # 可连接图块族(道路/管道/铁轨):base → {straight/end/corner/
                        # tee/cross: 帧名},运行时 tileVariant() 按邻接掩码选帧+旋转。
                        "tileFamilies": {
                            str(base)[:64]: {
                                str(slot)[:16]: str(frame)[:64]
                                for slot, frame in family.items()
                                if isinstance(frame, str) and frame
                            }
                            for base, family in (raw_families.items() if isinstance(raw_families, dict) else ())
                            if isinstance(family, dict) and family
                        },
                    }
                )
        elif kind == "tilemap" and tilemap is None:
            tilemap = {
                "key": key,
                "layer": str(raw.get("layer") or "World")[:64],
                "tilesetKey": str(raw.get("tileset_key") or "tileset")[:64],
                "tilesetName": str(raw.get("tileset_name") or "gameweave")[:64],
                "tileSize": _number(raw.get("tile_size"), 32, 8, 256),
                "solidGids": [
                    int(gid)
                    for gid in (raw.get("solid_gids") or [])
                    if isinstance(gid, (int, float)) and not isinstance(gid, bool)
                ],
            }
        entries.append(entry)
        if kind == "image":
            if "background" in key:
                # 场景变体(background, background-2...)全部收集;它们是舞台
                # 不是演员,一张都不能漏进 player/enemy 回退键。
                backgrounds.append(key)
                # 素材管线实测过亮度的背景带 luma(0-255):越暗的图运行时压暗
                # 蒙版越轻,避免"prompt 暗 + 蒙版再暗"叠出纯黑画面。没有 luma
                # 的旧 manifest 不进表,运行时用默认 dim。
                luma = raw.get("luma")
                if isinstance(luma, (int, float)) and not isinstance(luma, bool):
                    backdrop_dims[key] = round(max(0.0, min(0.35, (float(luma) - 40.0) / 220.0)), 3)
            elif str(raw.get("role") or "") == "tileset" or "tile" in key:
                pass  # tileset 图片不是演员,别污染 player/enemy 回退键
            else:
                image_keys.append(key)
    keys = {
        "background": backgrounds[0] if backgrounds else "",
        # 全部场景背景变体(主场景/高压阶段/换区),按生成顺序;
        # gameplay 代码按阶段切换 Backdrop.draw(scene, dim, key)。
        "backgrounds": backgrounds,
        "player": image_keys[0] if image_keys else "player-fallback",
        "enemy": image_keys[1] if len(image_keys) > 1 else "enemy-fallback",
        "reward": "reward-fallback",
    }
    return entries, keys, sheets, tilemap, backdrop_dims, sprite_demand_manifest


def _level_layout_px(design: dict, width: int, height: int) -> dict | None:
    """design.level_layout (cell grid) → pixel-space geometry for gameConfig.

    规划层已把布局钳成合法网格;这里一次性换算成像素矩形/路点,运行时代码
    (LevelLayout.ts、作者代码)零网格数学。返回 None = 设计没给布局。
    """
    layout = design.get("level_layout") if isinstance(design, dict) else None
    if not isinstance(layout, dict):
        return None
    grid = layout.get("grid") or {}
    cols = _number(grid.get("cols"), 24, 4, 96)
    rows = _number(grid.get("rows"), 14, 4, 64)
    cell_w = width / cols
    cell_h = height / rows

    def _rect(span) -> dict | None:
        if not isinstance(span, (list, tuple)) or len(span) < 4:
            return None
        c0, r0, c1, r1 = (int(v) for v in span[:4])
        return {
            "x": round(c0 * cell_w, 1),
            "y": round(r0 * cell_h, 1),
            "width": round((c1 - c0 + 1) * cell_w, 1),
            "height": round((r1 - r0 + 1) * cell_h, 1),
        }

    def _center(cell) -> dict | None:
        if not isinstance(cell, (list, tuple)) or len(cell) < 2:
            return None
        return {"x": round((int(cell[0]) + 0.5) * cell_w, 1), "y": round((int(cell[1]) + 0.5) * cell_h, 1)}

    walls = [rect for rect in (_rect(span) for span in layout.get("walls") or []) if rect]
    cover = [rect for rect in (_rect([c[0], c[1], c[0], c[1]]) for c in layout.get("cover") or [] if isinstance(c, (list, tuple)) and len(c) >= 2) if rect]
    regions = []
    for region in layout.get("regions") or []:
        if not isinstance(region, dict):
            continue
        rect = _rect(region.get("cells"))
        if rect:
            regions.append({"id": str(region.get("id") or ""), "name": str(region.get("name") or ""), "kind": str(region.get("kind") or "zone"), **rect})
    paths = []
    for path in layout.get("paths") or []:
        if not isinstance(path, dict):
            continue
        points = [pt for pt in (_center(cell) for cell in path.get("points") or []) if pt]
        if len(points) >= 2:
            paths.append({"id": str(path.get("id") or ""), "points": points})
    points = []
    for marker in layout.get("points") or []:
        if not isinstance(marker, dict):
            continue
        at = _center(marker.get("at"))
        if at:
            points.append({"id": str(marker.get("id") or ""), "kind": str(marker.get("kind") or "marker"), **at})
    if not (walls or cover or paths or regions or points):
        return None
    return {
        "cellWidth": round(cell_w, 2),
        "cellHeight": round(cell_h, 2),
        "regions": regions,
        "walls": walls,
        "cover": cover,
        "paths": paths,
        "points": points,
    }


def create_modular_phaser_project(
    spec: dict,
    design: dict,
    balance: dict | None = None,
    asset_manifest: dict | None = None,
) -> list[dict]:
    """Create a neutral, typed stage that an authoring agent grows into the game."""
    balance = balance or {}
    design = design if isinstance(design, dict) else {}
    title = str(spec.get("title") or "GameWeave Game")[:120]
    archetype = str(spec.get("archetype") or design.get("archetype") or "topdown_collect")
    controls = design.get("controls") if isinstance(design.get("controls"), dict) else {}
    hint = str(controls.get("hint") or "Move with arrows or WASD.")[:240]
    screen = design.get("screen") if isinstance(design.get("screen"), dict) else {}
    assets, asset_keys, sheets, tilemap, backdrop_dims, sprite_demand_manifest = _asset_catalog(asset_manifest)
    palette = _palette_for(spec, design)
    width = _number(screen.get("width"), 1152, 640, 1600)
    height = _number(screen.get("height"), 768, 480, 1000)
    config = {
        "title": title,
        "archetype": archetype,
        "width": width,
        "height": height,
        "palette": palette,
        "hint": hint,
        "lives": _number(balance.get("lives"), 3, 1, 9),
        "targetScore": _number(balance.get("target_score"), 120, 20, 5000),
        "params": _free_params(balance, design),
        "assets": assets,
        "assetKeys": asset_keys,
        "backdropDims": backdrop_dims,
        "sheet": sheets[0] if sheets else None,
        "sheets": sheets,
        "tilemap": tilemap,
        "levelLayout": _level_layout_px(design, width, height),
        "interactionProfiles": (
            list(design.get("interaction_profiles") or [])[:24]
            if isinstance(design.get("interaction_profiles"), list)
            else []
        ),
        "spriteDemandManifest": sprite_demand_manifest,
    }
    config_json = json.dumps(config, ensure_ascii=False, indent=2)
    package_json = json.dumps(
        {
            "name": "gameweave-generated-game",
            "private": True,
            "version": "0.0.0",
            "type": "module",
            "scripts": {
                "typecheck": "tsc --noEmit",
                "build": "tsc --noEmit && vite build",
            },
            "dependencies": {"phaser": "3.90.0"},
            "devDependencies": {"typescript": "5.8.3", "vite": "6.4.3"},
        },
        indent=2,
    )

    files = [
        text_artifact("package.json", package_json),
        text_artifact(
            "tsconfig.json",
            json.dumps(
                {
                    "compilerOptions": {
                        "target": "ES2020",
                        "module": "ESNext",
                        "lib": ["ES2020", "DOM", "DOM.Iterable"],
                        "moduleResolution": "Bundler",
                        "resolveJsonModule": True,
                        "useDefineForClassFields": True,
                        "strict": True,
                        "noEmit": True,
                        "skipLibCheck": True,
                    },
                    "include": ["src"],
                },
                indent=2,
            ),
        ),
        text_artifact(
            "index.html",
            INDEX_HTML.replace("__TITLE__", escape(title)),
        ),
        text_artifact(
            "src/config/gameConfig.ts",
            GAME_CONFIG_TS.replace("__CONFIG__", config_json),
        ),
        text_artifact(
            "src/systems/Colors.ts",
            COLORS_TS,
        ),
        text_artifact(
            "src/systems/Probe.ts",
            PROBE_TS,
        ),
        text_artifact(
            "src/systems/InputRouter.ts",
            INPUT_ROUTER_TS,
        ),
        text_artifact(
            "src/systems/Backdrop.ts",
            BACKDROP_TS,
        ),
        text_artifact(
            "src/systems/AreaHint.ts",
            AREA_HINT_TS,
        ),
        text_artifact(
            "src/systems/LevelLayout.ts",
            LEVEL_LAYOUT_TS,
        ),
        text_artifact(
            "src/systems/Bounds.ts",
            BOUNDS_TS,
        ),
        text_artifact(
            "src/systems/GameState.ts",
            GAME_STATE_TS,
        ),
        text_artifact(
            "src/systems/GameWeaveBridge.ts",
            GAME_WEAVE_BRIDGE_TS,
        ),
        text_artifact(
            "src/systems/Sfx.ts",
            SFX_TS,
        ),
        text_artifact(
            "src/systems/Juice.ts",
            JUICE_TS,
        ),
        text_artifact(
            "src/entities/Player.ts",
            PLAYER_TS,
        ),
        text_artifact(
            "src/ui/Hud.ts",
            HUD_TS,
        ),
        text_artifact(
            "src/scenes/BootScene.ts",
            BOOT_SCENE_TS,
        ),
        text_artifact(
            "src/scenes/TitleScene.ts",
            TITLE_SCENE_TS,
        ),
        text_artifact(
            "src/scenes/PlayScene.ts",
            PLAY_SCENE_TS,
        ),
        text_artifact(
            "src/scenes/GameOverScene.ts",
            GAME_OVER_SCENE_TS,
        ),
        text_artifact(
            "src/main.ts",
            MAIN_TS,
        ),
        text_artifact(
            "src/styles.css",
            STYLES_CSS.replace("__BG__", palette["bg"]),
        ),
    ]
    return files


def is_modular_phaser_project(files: list[dict] | None) -> bool:
    paths = {str(item.get("path") or "") for item in (files or [])}
    return {"package.json", "index.html", "tsconfig.json", "src/main.ts"}.issubset(paths)


@lru_cache(maxsize=1)
def scaffold_source_paths() -> frozenset[str]:
    """Every path the neutral scaffold ships. Files OUTSIDE this set were added
    by authoring/repair agents — QA uses that to spot accepted author modules
    that never got wired into the entry import graph (orphan modules)."""
    return frozenset(str(item.get("path") or "") for item in create_modular_phaser_project({}, {}))


def safe_project_source_path(path: str) -> bool:
    normalized = str(path or "").replace("\\", "/").lstrip("./")
    return bool(
        normalized
        and not normalized.startswith(("/", "node_modules/", "dist/"))
        and ".." not in normalized.split("/")
        and re.fullmatch(r"[A-Za-z0-9._/-]{1,180}", normalized)
        and normalized.endswith((".ts", ".tsx", ".js", ".mjs", ".css", ".json", ".html", ".md"))
    )


__all__ = [
    "create_modular_phaser_project",
    "is_modular_phaser_project",
    "safe_project_source_path",
    "scaffold_source_paths",
]
