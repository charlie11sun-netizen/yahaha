"""Gameplay-family routing and advisory balance planning helpers."""

import re

from app.agents.nodes_common import _ARCHETYPES, _ARCHETYPES_3D, _has_any


_LEGACY_GENRE_TO_ARCHETYPE = {
    "shooter": "vertical_shooter",
    "puzzle": "logic_grid",
    "runner": "lane_runner",
    "collector": "topdown_collect",
}


def _native_archetype(genre: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", genre.lower()).strip("_")
    return slug or "custom_2d"


def _route_archetype(spec: dict, prompt: str, brief: dict | None = None, mechanics: dict | None = None) -> dict:
    genre = str(spec.get("genre") or "").strip().lower()
    explicit_family = _LEGACY_GENRE_TO_ARCHETYPE.get(genre)
    if explicit_family:
        meta = _ARCHETYPES[explicit_family]
        return {
            "archetype": explicit_family,
            "genre": genre,
            "label": meta["label"],
            "core_loop": spec.get("core_loop") or meta["loop"],
            "reason": f"model genre: {genre}",
            "legacy_family": True,
        }
    if genre and genre != "arcade":
        archetype = _native_archetype(genre)
        return {
            "archetype": archetype,
            "genre": genre,
            "label": f"model-authored {genre.replace('_', ' ')}",
            "core_loop": spec.get("core_loop") or "implement the model-authored core loop",
            "reason": "model genre preserved; no legacy template coercion",
            "legacy_family": False,
        }
    if mechanics and mechanics.get("archetype_hint") in _ARCHETYPES:
        archetype = mechanics["archetype_hint"]
        meta = _ARCHETYPES[archetype]
        return {"archetype": archetype, "genre": meta["genre"], "label": meta["label"], "core_loop": meta["loop"], "reason": "mechanic planner hint for generic arcade genre", "legacy_family": True}
    text = " ".join(
        str(value)
        for value in [
            prompt,
            (brief or {}).get("player_fantasy"),
            (brief or {}).get("objective"),
            " ".join((brief or {}).get("mechanic_requirements") or []),
            spec.get("title"),
            spec.get("genre"),
            spec.get("theme"),
            spec.get("core_loop"),
            " ".join(spec.get("tags") or []),
        ]
        if value
    ).lower()
    if _has_any(text, ["shoot", "shmup", "raiden", "bullet", "fighter", "战机", "雷霆", "飞机大战", "打飞机", "射击", "弹幕", "空战", "spaceship", "plane"]):
        archetype = "vertical_shooter"
        reason = "shooter/plane keywords"
    elif _has_any(text, ["puzzle", "logic", "pipe", "circuit", "rune", "connect", "解谜", "逻辑", "连接", "方块"]):
        archetype = "logic_grid"
        reason = "logic/connect keywords"
    elif _has_any(text, ["runner", "race", "lane", "dash", "dodge", "run", "躲", "跑", "赛道", "漂移"]):
        archetype = "lane_runner"
        reason = "runner/dodge keywords"
    elif _has_any(text, ["collect", "coin", "gem", "miner", "fish", "koi", "forest", "explore", "收集", "金币", "矿", "鱼", "森林", "宝石"]):
        archetype = "topdown_collect"
        reason = "collection/exploration keywords"
    else:
        archetype = "topdown_collect"
        reason = f"generic arcade fallback: {genre or 'unspecified'}"
    meta = _ARCHETYPES[archetype]
    return {"archetype": archetype, "genre": meta["genre"], "label": meta["label"], "core_loop": meta["loop"], "reason": reason, "legacy_family": True}


def _route_archetype_3d(spec: dict, prompt: str, brief: dict | None = None, mechanics: dict | None = None) -> dict:
    """3D 路由：信模型给的 genre，不再用易误判的关键词级联（旧版会把 spec 里出现 "track"/
    "car" 的射击 prompt 误判成 racer_3d，还会盖掉模型自己的判断）。fps_arena 的最终确认放到
    game_design 之后，由设计里的 scene.camera 回校——见 _reconcile_archetype_3d。
    prompt / brief / mechanics 不再参与 3D 路由（签名保留以兼容调用点）。"""
    genre = str(spec.get("genre") or "").lower()
    archetype = "fps_arena" if genre == "shooter" else "runner_3d" if genre == "runner" else "collector_3d"
    reason = f"model genre: {genre or 'arcade'}"
    meta = _ARCHETYPES_3D[archetype]
    return {"archetype": archetype, "genre": meta["genre"], "label": meta["label"], "core_loop": meta["loop"], "reason": reason}


def _reconcile_archetype_3d(spec: dict, design: dict) -> str:
    """game_design 之后，用模型真正画出的相机校正 3D archetype（QA 门 / GENRE FIDELITY /
    replan 兜底都依赖它）：first_person ⇒ fps_arena；明确非第一人称却被标成 fps ⇒ 退回 runner_3d。"""
    cam = str(((design or {}).get("scene") or {}).get("camera") or "").lower()
    cur = str(spec.get("archetype") or "")
    if cam == "first_person":
        return "fps_arena"
    if cam in ("third_person", "chase", "orbit") and cur == "fps_arena":
        return "runner_3d"
    return cur if cur in _ARCHETYPES_3D else "fps_arena"


def _difficulty_factor(prompt: str) -> float:
    p = prompt.lower()
    if _has_any(p, ["hard", "difficult", "expert", "困难", "高难", "挑战"]):
        return 1.08
    if _has_any(p, ["easy", "relax", "cozy", "简单", "休闲", "轻松"]):
        return 0.9
    return 1.0


def _decision_timing_model(spec: dict, prompt: str) -> str:
    text = " ".join(
        str(value)
        for value in (spec.get("genre"), spec.get("core_loop"), prompt)
        if value
    ).lower()
    if _has_any(text, ["turn-based", "turn based", "turn_based", "per turn", "回合"]):
        return "turn_based"
    if _has_any(text, ["puzzle", "logic", "card", "board", "strategy", "解谜", "策略", "棋", "牌"]):
        return "discrete"
    return "model_authored"


def _balance_plan(archetype: str, spec: dict, prompt: str) -> dict:
    factor = _difficulty_factor(prompt)
    if archetype not in _ARCHETYPES:
        return {
            "mode": "design_driven",
            "genre": str(spec.get("genre") or archetype),
            "timing_model": _decision_timing_model(spec, prompt),
            "decision_model": "model_authored",
            "qa": {
                "requires_genre_fidelity": True,
                "requires_reachable_win_loss": True,
                "requires_readable_feedback": True,
            },
        }
    if archetype == "logic_grid":
        return {
            "mode": "decision_driven",
            "timing_model": "discrete",
            "decision_model": "move_efficiency",
            "decision_window_seconds": int(72 / max(0.92, min(1.12, factor))),
            "hint_delay_seconds": 18,
            "qa": {
                "min_decision_window_seconds": 45,
                "requires_solution_path": True,
                "requires_readable_board_state": True,
            },
        }
    if archetype == "lane_runner":
        return {
            "round_seconds": 60,
            "target_score": int(185 * factor),
            "lives": 4,
            "player_speed": 280,
            "hazard_speed": int(135 * factor),
            "hazard_spawn_ms": int(1450 / factor),
            "collectible_speed": int(110 * factor),
            "collectible_spawn_ms": 780,
            "max_hazards": 6,
            "lanes": 3,
            "qa": {"min_reaction_ms": 980, "max_obstacle_density": 7.5},
        }
    return {
        "round_seconds": 65,
        "target_score": int(170 * factor),
        "lives": 4,
        "player_speed": int(330 / max(0.95, min(1.04, factor))),
        "hazard_speed": int(92 * factor),
        "hazard_spawn_ms": int(1750 / factor),
        "collectible_speed": 80,
        "collectible_spawn_ms": 720,
        "max_hazards": 6,
        "lanes": 3,
        "qa": {"min_reaction_ms": 1200, "min_player_to_hazard_ratio": 2.6, "max_obstacle_density": 6.5},
    }


def _merge_balance_into_design(design: dict, archetype: str, balance: dict) -> dict:
    """挂上 archetype 元数据与可选的 balance 默认值。

    只补缺不覆盖：模型设计给出的节奏（survive_seconds 等）优先——写死的
    balance 表覆盖模型数值曾是产出同质化的来源之一。balance 本身作为
    advisory 默认值原样带给作者 agent，用不用由玩法代码决定。
    """
    merged = dict(design or {})
    merged["archetype"] = archetype
    rules = dict(merged.get("rules") if isinstance(merged.get("rules"), dict) else {})
    if balance.get("round_seconds") is not None:
        rules.setdefault("survive_seconds", balance["round_seconds"])
    merged["rules"] = rules
    merged["balance"] = balance
    return merged




__all__ = [
    "_route_archetype",
    "_route_archetype_3d",
    "_reconcile_archetype_3d",
    "_difficulty_factor",
    "_balance_plan",
    "_merge_balance_into_design",
]
