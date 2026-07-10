"""Archetype routing and balance planning helpers."""

from app.agents.nodes_common import _ARCHETYPES, _ARCHETYPES_3D, _has_any


def _route_archetype(spec: dict, prompt: str, brief: dict | None = None, mechanics: dict | None = None) -> dict:
    if mechanics and mechanics.get("archetype_hint") in _ARCHETYPES:
        archetype = mechanics["archetype_hint"]
        meta = _ARCHETYPES[archetype]
        return {"archetype": archetype, "genre": meta["genre"], "label": meta["label"], "core_loop": meta["loop"], "reason": "mechanic planner hint"}
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
        genre = str(spec.get("genre") or "").lower()
        archetype = "vertical_shooter" if genre == "shooter" else "logic_grid" if genre == "puzzle" else "lane_runner" if genre == "runner" else "topdown_collect"
        reason = f"genre fallback: {genre or 'arcade'}"
    meta = _ARCHETYPES[archetype]
    return {"archetype": archetype, "genre": meta["genre"], "label": meta["label"], "core_loop": meta["loop"], "reason": reason}


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


def _balance_plan(archetype: str, spec: dict, prompt: str) -> dict:
    factor = _difficulty_factor(prompt)
    if archetype == "logic_grid":
        return {
            "round_seconds": int(72 / max(0.92, min(1.12, factor))),
            "target_score": 360,
            "lives": 3,
            "player_speed": 260,
            "hazard_speed": 120,
            "hazard_spawn_ms": 1400,
            "collectible_speed": 120,
            "collectible_spawn_ms": 900,
            "max_hazards": 4,
            "lanes": 3,
            "qa": {"min_round_seconds": 45, "requires_solution_path": True},
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
    merged = dict(design or {})
    merged["archetype"] = archetype
    rules = dict(merged.get("rules") if isinstance(merged.get("rules"), dict) else {})
    rules["survive_seconds"] = balance.get("round_seconds", rules.get("survive_seconds", 55))
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
