"""Pure game specification and design normalization helpers."""

import json

from app.agents.nodes_common import (
    _ARCHETYPES,
    _ARCHETYPES_3D,
    _THEMES,
    _THEME_COVER,
    _has_any,
    bundles,
)


def _detect_theme(prompt: str) -> str:
    p = prompt.lower()
    if _has_any(p, ["space", "star", "asteroid", "rocket", "太空", "星", "飞船"]):
        return "space"
    if _has_any(p, ["neon", "cyber", "霓虹", "赛博"]):
        return "neon"
    if _has_any(p, ["forest", "tree", "magic", "森林", "魔法"]):
        return "forest"
    if _has_any(p, ["ocean", "sea", "fish", "koi", "海", "鱼"]):
        return "ocean"
    if _has_any(p, ["candy", "sweet", "糖"]):
        return "candy"
    return next((theme for theme in _THEMES if theme in p), "retro")


def _detect_genre(prompt: str) -> str:
    p = prompt.lower()
    if _has_any(p, ["shoot", "shmup", "raiden", "bullet hell", "fighter jet", "战机", "雷霆", "飞机大战", "打飞机", "射击", "弹幕", "空战"]):
        return "shooter"
    if _has_any(p, ["puzzle", "logic", "pipe", "circuit", "rune", "match", "解谜", "逻辑", "连接", "方块"]):
        return "puzzle"
    if _has_any(p, ["runner", "race", "dodge", "lane", "run", "dash", "躲", "跑", "赛道", "漂移"]):
        return "runner"
    return "arcade"


def _theme_cover(theme) -> str:
    text = str(theme or "").lower()
    exact = _THEME_COVER.get(text)
    if exact:
        return exact
    return _THEME_COVER.get(_detect_theme(text), _THEME_COVER["retro"])


def structured_text(value: object, *, limit: int, preferred_keys: tuple[str, ...] = ()) -> str:
    """Turn model-authored structured prose into readable prompt text, never Python repr."""
    if value is None:
        return ""
    if isinstance(value, str):
        return " ".join(value.split())[:limit]
    if isinstance(value, dict):
        keys = [key for key in preferred_keys if key in value]
        if not keys:
            keys = list(value)[:8]
        parts = []
        for key in keys:
            text = structured_text(value.get(key), limit=max(40, limit // 2))
            if text:
                parts.append(f"{key}: {text}")
        return "; ".join(parts)[:limit]
    if isinstance(value, (list, tuple, set)):
        parts = [
            structured_text(item, limit=max(40, limit // 3))
            for item in list(value)[:10]
        ]
        return "; ".join(item for item in parts if item)[:limit]
    try:
        return " ".join(str(value).split())[:limit]
    except Exception:  # noqa: BLE001 - model normalization is fail-open
        return json.dumps(value, ensure_ascii=False, default=str)[:limit]


# Compatibility for callers that used the helper before it became a public
# cross-module utility.  New modules should import structured_text instead.
_structured_text = structured_text


def _heuristic_spec(prompt: str) -> dict:
    genre = _detect_genre(prompt)
    theme = _detect_theme(prompt)
    controls = {
        "keyboard": ["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"],
        "pointer": ["move"],
        "hint": "move with mouse / arrows, collect rewards, avoid hazards",
    }
    if genre == "shooter":
        controls = {"keyboard": ["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Space fire"], "pointer": ["move", "hold to fire"], "hint": "fly with arrows / mouse, hold to fire, dodge bullets, defeat the boss"}
    elif genre == "puzzle":
        controls = {"keyboard": ["Space restart"], "pointer": ["click tiles"], "hint": "click tiles to rotate the path"}
    elif genre == "runner":
        controls = {"keyboard": ["ArrowLeft", "ArrowRight"], "pointer": ["tap left/right"], "hint": "switch lanes, collect bonuses, avoid blockers"}
    return {
        "title": bundles.title_from(prompt),
        "summary": (prompt[:117] + "...") if len(prompt) > 120 else prompt,
        "genre": genre,
        "theme": theme,
        "target_runtime": "phaser-vite",
        "core_loop": _ARCHETYPES["vertical_shooter" if genre == "shooter" else "logic_grid" if genre == "puzzle" else "lane_runner" if genre == "runner" else "topdown_collect"]["loop"],
        "controls": controls,
        "win_condition": "reach_target_score",
        "lose_condition": "timer_or_lives_depleted",
        "score_rule": "reward collection and efficient play",
        "difficulty_curve": "gentle opening, gradual pressure increase, no instant failure",
        "visual_style": theme,
        "tags": [theme, genre, "casual"],
    }


def _coerce_spec(data: dict, prompt: str) -> dict:
    base = _heuristic_spec(prompt)
    if isinstance(data, dict):
        text_fields = {
            "title": (120, ("name", "title")),
            "summary": (500, ("summary", "overview", "fantasy")),
            "genre": (80, ("name", "genre", "label", "type")),
            "theme": (400, ("setting", "tone", "visual_style", "art_direction", "palette", "name")),
            "core_loop": (1200, ("campaign", "run", "combat", "turn", "loop", "progression")),
            "win_condition": (500, ("primary", "win", "victory")),
            "lose_condition": (500, ("primary", "lose", "defeat")),
            "score_rule": (500, ("score", "rewards", "calculation")),
            "difficulty_curve": (500, ("opening", "midgame", "late_game", "boss", "curve")),
            "visual_style": (500, ("style", "art_direction", "palette", "readability", "effects")),
        }
        for key, (limit, preferred_keys) in text_fields.items():
            if data.get(key) is not None:
                normalized = structured_text(
                    data[key],
                    limit=limit,
                    preferred_keys=preferred_keys,
                )
                if normalized:
                    base[key] = normalized
        if isinstance(data.get("tags"), list) and data["tags"]:
            base["tags"] = [str(tag)[:30] for tag in data["tags"]][:5]
        if isinstance(data.get("controls"), dict):
            base["controls"].update(data["controls"])
    return base


def _heuristic_design(spec: dict) -> dict:
    archetype = spec.get("archetype") or ("logic_grid" if spec.get("genre") == "puzzle" else "lane_runner" if spec.get("genre") == "runner" else "topdown_collect")
    if archetype not in _ARCHETYPES:
        entities = [
            {"name": "player", "type": "avatar", "movement": "genre_defined"},
            {"name": "objective", "type": "goal", "behavior": "defined by the GameSpec core loop"},
        ]
        rules = {
            "win": spec.get("win_condition") or "complete the authored objective",
            "lose": spec.get("lose_condition") or "reach the authored failure state",
        }
        ui = {
            "show_score": False,
            "show_timer": False,
            "show_lives": True,
            "show_restart_button": True,
        }
    elif archetype == "logic_grid":
        entities = [
            {"name": "tile", "type": "rotating_pipe", "movement": "click_rotate"},
            {"name": "source", "type": "beacon", "spawn": "left_edge"},
            {"name": "exit", "type": "beacon", "spawn": "right_edge"},
        ]
        rules = {"connect_left_to_right": "win", "timer_zero": "fail", "survive_seconds": 70}
        ui = {"show_score": True, "show_timer": True, "show_lives": True, "show_restart_button": True}
    elif archetype == "lane_runner":
        entities = [
            {"name": "runner", "type": "avatar", "movement": "lane_switch"},
            {"name": "blocker", "type": "obstacle", "spawn": "lane_top"},
            {"name": "bonus", "type": "collectible", "spawn": "lane_top"},
        ]
        rules = {"collision_player_hazard": "lose_life", "collision_player_star": "score_plus_18", "survive_seconds": 55}
        ui = {"show_score": True, "show_timer": True, "show_lives": True, "show_restart_button": True}
    else:
        entities = [
            {"name": "player", "type": "avatar", "movement": "top_down"},
            {"name": "hazard", "type": "obstacle", "spawn": "arena_edge"},
            {"name": "reward", "type": "collectible", "spawn": "safe_arena"},
        ]
        rules = {"collision_player_hazard": "lose_life", "collision_player_star": "score_plus_combo", "survive_seconds": 55}
        ui = {"show_score": True, "show_timer": True, "show_lives": True, "show_restart_button": True}
    return {
        "archetype": archetype,
        "screen": {"width": 900, "height": 600},
        "entities": entities,
        "rules": rules,
        "ui": ui,
    }


def _coerce_level_layout(data) -> dict | None:
    """Normalize the model-authored level_layout into a safe, bounded shape.

    坐标全部钳进网格、畸形条目静默丢弃、数量封顶——布局是"背景构图 + 碰撞
    几何 + 敌人路线"的共同事实源,坏一条脏数据会同时毒三条链路。返回 None
    表示设计没给出可用布局(管线各消费方都必须容忍缺失)。
    """
    if not isinstance(data, dict):
        return None
    grid = data.get("grid") if isinstance(data.get("grid"), dict) else {}

    def _dim(value, default: int, lo: int, hi: int) -> int:
        try:
            parsed = int(float(value))
        except (TypeError, ValueError):
            parsed = default
        return max(lo, min(hi, parsed))

    cols = _dim(grid.get("cols"), 24, 8, 48)
    rows = _dim(grid.get("rows"), 14, 6, 32)

    def _cell(raw) -> list[int] | None:
        if not isinstance(raw, (list, tuple)) or len(raw) < 2:
            return None
        try:
            c, r = int(float(raw[0])), int(float(raw[1]))
        except (TypeError, ValueError):
            return None
        return [max(0, min(cols - 1, c)), max(0, min(rows - 1, r))]

    def _span(raw) -> list[int] | None:
        if not isinstance(raw, (list, tuple)) or len(raw) < 4:
            return None
        try:
            values = [int(float(v)) for v in raw[:4]]
        except (TypeError, ValueError):
            return None
        c0, r0, c1, r1 = values
        c0, c1 = sorted((max(0, min(cols - 1, c0)), max(0, min(cols - 1, c1))))
        r0, r1 = sorted((max(0, min(rows - 1, r0)), max(0, min(rows - 1, r1))))
        return [c0, r0, c1, r1]

    def _slug(value, fallback: str) -> str:
        text = " ".join(str(value or "").split())
        return (text or fallback)[:48]

    walls = [span for span in (_span(raw) for raw in (data.get("walls") or [])[:60]) if span][:40]
    cover = [cell for cell in (_cell(raw) for raw in (data.get("cover") or [])[:40]) if cell][:24]
    regions: list[dict] = []
    for index, raw in enumerate((data.get("regions") or [])[:10]):
        if not isinstance(raw, dict):
            continue
        span = _span(raw.get("cells") or raw.get("rect"))
        if span is None:
            continue
        regions.append(
            {
                "id": _slug(raw.get("id"), f"region_{index + 1}"),
                "name": _slug(raw.get("name") or raw.get("id"), f"Area {index + 1}"),
                "cells": span,
                "kind": _slug(raw.get("kind"), "zone"),
            }
        )
        if len(regions) >= 6:
            break
    paths: list[dict] = []
    for index, raw in enumerate((data.get("paths") or [])[:12]):
        if not isinstance(raw, dict):
            continue
        points = [cell for cell in (_cell(p) for p in (raw.get("points") or [])[:24]) if cell][:16]
        if len(points) < 2:
            continue
        paths.append({"id": _slug(raw.get("id"), f"path_{index + 1}"), "points": points})
        if len(paths) >= 8:
            break
    points: list[dict] = []
    for index, raw in enumerate((data.get("points") or [])[:24]):
        if not isinstance(raw, dict):
            continue
        cell = _cell(raw.get("at") or raw.get("cell"))
        if cell is None:
            continue
        points.append(
            {
                "id": _slug(raw.get("id"), f"point_{index + 1}"),
                "kind": _slug(raw.get("kind"), "marker").lower(),
                "at": cell,
            }
        )
        if len(points) >= 16:
            break
    if not (walls or cover or paths or regions):
        return None
    if not any(point.get("kind") == "spawn" for point in points):
        points.insert(0, {"id": "player_spawn", "kind": "spawn", "at": [cols // 2, rows // 2]})
    return {
        "grid": {"cols": cols, "rows": rows},
        "regions": regions,
        "walls": walls,
        "cover": cover,
        "paths": paths,
        "points": points,
    }


def _coerce_design(data: dict, spec: dict | None = None) -> dict:
    base = _heuristic_design(spec or {})
    if isinstance(data, dict):
        if isinstance(data.get("screen"), dict):
            base["screen"].update(data["screen"])
        if isinstance(data.get("entities"), list) and data["entities"]:
            base["entities"] = data["entities"][:10]
        if isinstance(data.get("rules"), dict):
            base["rules"].update(data["rules"])
        if isinstance(data.get("ui"), dict):
            base["ui"].update(data["ui"])
        # 模型优先：保留 GameDesignAgent 产出的丰富结构，原样喂给 Coder
        # ("scene" 是 3D 设计的相机/环境/空间，必须保留；palette/signature_twist/
        # sfx_events 是每局的视觉身份、辨识度机制与音效清单)
        for key in (
            "scene",
            "background",
            "player",
            "waves",
            "powerups",
            "boss",
            "juice",
            "palette",
            "signature_twist",
            "sfx_events",
            "interaction_profiles",
        ):
            if data.get(key):
                base[key] = (
                    list(data[key])[:24]
                    if key == "interaction_profiles" and isinstance(data[key], list)
                    else data[key]
                )
        layout = _coerce_level_layout(data.get("level_layout"))
        if layout:
            base["level_layout"] = layout
    return base


def _simplify_design(design: dict) -> dict:
    current = design or {}
    archetype = current.get("archetype") or "topdown_collect"
    if archetype not in _ARCHETYPES:
        simplified = {
            key: current[key]
            for key in (
                "archetype",
                "screen",
                "background",
                "level_layout",
                "player",
                "rules",
                "ui",
                "palette",
                "signature_twist",
                "sfx_events",
                "boss",
                "interaction_profiles",
            )
            if current.get(key) is not None
        }
        simplified["entities"] = list(current.get("entities") or [])[:6]
        simplified["waves"] = list(current.get("waves") or [])[:3]
        simplified["scope_simplified"] = True
        return simplified
    spec = {"archetype": archetype, "genre": _ARCHETYPES.get(archetype, _ARCHETYPES["topdown_collect"])["genre"]}
    simplified = _heuristic_design(spec)
    simplified["rules"]["survive_seconds"] = 50
    if isinstance(current.get("interaction_profiles"), list):
        simplified["interaction_profiles"] = list(current["interaction_profiles"])[:12]
    return simplified


def _simplify_design_3d(design: dict) -> dict:
    """3D replan 兜底：模型不可用时给一个最小可实现的 3D 设计（仍是 3D，不回退 2D）。"""
    current = design or {}
    archetype = current.get("archetype") if current.get("archetype") in _ARCHETYPES_3D else "fps_arena"
    meta = _ARCHETYPES_3D[archetype]
    simplified = {
        "archetype": archetype,
        "scene": {
            "camera": "first_person" if archetype == "fps_arena" else "third_person",
            "fov": 72,
            "environment": "dark arena with fog and a glowing grid floor",
            "space": "a bounded arena the player stays inside",
        },
        "player": {"visual": "simple primitive avatar", "controls": "WASD + mouse", "abilities": ["move", "act"]},
        "entities": [{"name": "drone", "role": "enemy", "visual": "emissive low-poly shape", "movement": "homes toward the player", "behavior": "advance and threaten"}],
        "waves": [{"t": 0, "spawn": "few", "note": "safe opening"}, {"t": 12, "spawn": "more", "note": "ramp up"}],
        "rules": {"win": "survive / clear waves", "lose": "hp depleted", "survive_seconds": 60, "score": "per kill / pickup"},
        "ui": {"show_score": True, "show_lives": True, "show_restart_button": True, "crosshair": archetype == "fps_arena"},
        "core_loop": meta["loop"],
    }
    if isinstance(current.get("interaction_profiles"), list):
        simplified["interaction_profiles"] = list(current["interaction_profiles"])[:12]
    return simplified



__all__ = [
    "structured_text",
    "_detect_theme",
    "_detect_genre",
    "_theme_cover",
    "_heuristic_spec",
    "_coerce_spec",
    "_heuristic_design",
    "_coerce_design",
    "_simplify_design",
    "_simplify_design_3d",
]
