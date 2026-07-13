"""Pure game specification and design normalization helpers."""

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
    return _THEME_COVER.get(str(theme or "").lower(), _THEME_COVER["retro"])


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
        for key in (
            "title",
            "summary",
            "genre",
            "theme",
            "core_loop",
            "win_condition",
            "lose_condition",
            "score_rule",
            "difficulty_curve",
            "visual_style",
        ):
            if data.get(key):
                base[key] = str(data[key])[:220]
        if isinstance(data.get("tags"), list) and data["tags"]:
            base["tags"] = [str(tag)[:30] for tag in data["tags"]][:5]
        if isinstance(data.get("controls"), dict):
            base["controls"].update(data["controls"])
    return base


def _heuristic_design(spec: dict) -> dict:
    archetype = spec.get("archetype") or ("logic_grid" if spec.get("genre") == "puzzle" else "lane_runner" if spec.get("genre") == "runner" else "topdown_collect")
    if archetype == "logic_grid":
        entities = [
            {"name": "tile", "type": "rotating_pipe", "movement": "click_rotate"},
            {"name": "source", "type": "beacon", "spawn": "left_edge"},
            {"name": "exit", "type": "beacon", "spawn": "right_edge"},
        ]
        rules = {"connect_left_to_right": "win", "timer_zero": "fail", "survive_seconds": 70}
    elif archetype == "lane_runner":
        entities = [
            {"name": "runner", "type": "avatar", "movement": "lane_switch"},
            {"name": "blocker", "type": "obstacle", "spawn": "lane_top"},
            {"name": "bonus", "type": "collectible", "spawn": "lane_top"},
        ]
        rules = {"collision_player_hazard": "lose_life", "collision_player_star": "score_plus_18", "survive_seconds": 55}
    else:
        entities = [
            {"name": "player", "type": "avatar", "movement": "top_down"},
            {"name": "hazard", "type": "obstacle", "spawn": "arena_edge"},
            {"name": "reward", "type": "collectible", "spawn": "safe_arena"},
        ]
        rules = {"collision_player_hazard": "lose_life", "collision_player_star": "score_plus_combo", "survive_seconds": 55}
    return {
        "archetype": archetype,
        "screen": {"width": 900, "height": 600},
        "entities": entities,
        "rules": rules,
        "ui": {"show_score": True, "show_timer": True, "show_lives": True, "show_restart_button": True},
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
        ):
            if data.get(key):
                base[key] = data[key]
    return base


def _simplify_design(design: dict) -> dict:
    current = design or {}
    archetype = current.get("archetype") or "topdown_collect"
    spec = {"archetype": archetype, "genre": _ARCHETYPES.get(archetype, _ARCHETYPES["topdown_collect"])["genre"]}
    simplified = _heuristic_design(spec)
    simplified["rules"]["survive_seconds"] = 50
    return simplified


def _simplify_design_3d(design: dict) -> dict:
    """3D replan 兜底：模型不可用时给一个最小可实现的 3D 设计（仍是 3D，不回退 2D）。"""
    current = design or {}
    archetype = current.get("archetype") if current.get("archetype") in _ARCHETYPES_3D else "fps_arena"
    meta = _ARCHETYPES_3D[archetype]
    return {
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



__all__ = [
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
