"""Planning and design nodes for the GameWeave LangGraph pipeline."""
# ruff: noqa: F401,F403,F405
from app.agents.nodes_common import *


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
        "target_runtime": "canvas",
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
        # ("scene" 是 3D 设计的相机/环境/空间，必须保留)
        for key in ("scene", "background", "player", "waves", "powerups", "boss", "juice"):
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


def _prompt_cues(prompt: str) -> list[str]:
    stop = {
        "make",
        "game",
        "with",
        "where",
        "that",
        "this",
        "into",
        "from",
        "using",
        "player",
        "players",
        "collect",
        "avoid",
        "survive",
        "seconds",
        "the",
        "and",
        "for",
        "you",
    }
    cues: list[str] = []
    for token in re.findall(r"[a-zA-Z][a-zA-Z0-9'-]{2,}", prompt.lower()):
        if token in stop or token in cues:
            continue
        cues.append(token)
        if len(cues) == 6:
            break
    return cues


def _controls_line(controls: dict) -> str:
    keys = controls.get("keyboard") if isinstance(controls.get("keyboard"), list) else []
    pointer = controls.get("pointer") if isinstance(controls.get("pointer"), list) else []
    parts = []
    if keys:
        parts.append("keyboard=" + ", ".join(str(key) for key in keys[:4]))
    if pointer:
        parts.append("pointer=" + ", ".join(str(item) for item in pointer[:3]))
    if controls.get("hint"):
        parts.append("hint=" + _clip(controls.get("hint"), 70))
    return "; ".join(parts) if parts else "default keyboard + pointer controls"


def _spec_log_lines(spec: dict, source: str) -> list[str]:
    controls = spec.get("controls") if isinstance(spec.get("controls"), dict) else {}
    tags = ", ".join(str(tag) for tag in (spec.get("tags") or [])[:5]) or "none"
    return [
        f"source: {source}",
        f"title: {_clip(spec.get('title'), 80)}",
        f"genre/theme/runtime: {spec.get('genre', 'arcade')} / {spec.get('theme', 'retro')} / {spec.get('target_runtime', 'canvas')}",
        f"core loop: {_clip(spec.get('core_loop'), 120)}",
        f"win/lose: {spec.get('win_condition', 'reach_target_score')} / {spec.get('lose_condition', 'timer_or_lives_depleted')}",
        f"controls: {_controls_line(controls)}",
        f"tags: {tags}",
    ]


def _entity_line(entity: dict) -> str:
    name = entity.get("name", "?")
    entity_type = entity.get("type", "?")
    movement = entity.get("movement") or entity.get("spawn") or entity.get("behavior") or "static"
    return f"{name}({entity_type}, {movement})"


def _design_log_lines(design: dict) -> list[str]:
    screen = design.get("screen") if isinstance(design.get("screen"), dict) else {}
    entities = design.get("entities") if isinstance(design.get("entities"), list) else []
    rules = design.get("rules") if isinstance(design.get("rules"), dict) else {}
    balance = design.get("balance") if isinstance(design.get("balance"), dict) else {}
    entity_text = ", ".join(_entity_line(entity) for entity in entities[:8]) or "none"
    rule_bits = []
    for key in ("collision_player_hazard", "collision_player_star", "connect_left_to_right", "survive_seconds"):
        if key in rules:
            rule_bits.append(f"{key}={rules[key]}")
    lines = [
        f"archetype: {design.get('archetype', 'unknown')}",
        f"screen: {screen.get('width', 900)}x{screen.get('height', 600)} canvas",
        f"entities: {entity_text}",
        "rules: " + (", ".join(str(bit) for bit in rule_bits) or "default game loop"),
    ]
    if balance:
        lines.append(
            "balance: "
            f"duration={balance.get('round_seconds')}s, target={balance.get('target_score')}, "
            f"lives={balance.get('lives')}, hazard_spawn={balance.get('hazard_spawn_ms')}ms"
        )
    return lines


def _asset_log_lines(uploaded: list[dict], manifest: dict, spec: dict) -> list[str]:
    lines = [f"uploaded references loaded: {len(uploaded)}"]
    for asset in uploaded[:4]:
        lines.append(f"reference: {asset.get('key')} ({asset.get('type', 'file')})")
    if len(uploaded) > 4:
        lines.append(f"reference overflow: {len(uploaded) - 4} additional asset(s)")
    lines.append(f"cover strategy: theme={spec.get('theme', 'retro')} -> {manifest.get('cover')}")
    lines.append(f"asset manifest entries: cover + {len(uploaded)} uploaded reference(s)")
    return lines


def _brief_keywords(prompt: str, spec: dict) -> list[str]:
    cues = _prompt_cues(prompt)
    for tag in spec.get("tags") or []:
        tag = str(tag).lower()
        if tag and tag not in cues:
            cues.append(tag)
    for word in re.findall(r"[\u4e00-\u9fff]{2,6}", prompt):
        if word not in cues:
            cues.append(word)
    return cues[:8]


def _heuristic_brief(prompt: str, spec: dict) -> dict:
    genre = str(spec.get("genre") or "arcade").lower()
    title = spec.get("title") or bundles.title_from(prompt)
    keywords = _brief_keywords(prompt, spec)
    if genre == "puzzle":
        verbs = ["inspect", "rotate", "connect", "optimize"]
        mechanics = ["visible solution path", "move-efficient scoring", "timed pressure"]
        fantasy = f"repair a living circuit in {title}"
    elif genre == "runner":
        verbs = ["switch lanes", "read patterns", "collect boosts", "recover from hits"]
        mechanics = ["lane telegraphing", "bonus chains", "forgiving lives", "late-round pressure"]
        fantasy = f"pilot the hero through a fast readable course in {title}"
    else:
        verbs = ["navigate", "collect", "bait hazards", "chain rewards"]
        mechanics = ["combo collection", "soft homing hazards", "temporary powerups", "safe opening"]
        fantasy = f"guide the hero through a compact arena in {title}"
    return {
        "player_fantasy": fantasy,
        "objective": spec.get("win_condition") or "reach the score goal before the round ends",
        "core_verbs": verbs,
        "mechanic_requirements": mechanics,
        "reward_loop": "small rewards every few seconds, larger payoff for chaining clean play",
        "difficulty_beats": ["0-10s tutorial-safe opening", "10-35s readable pattern pressure", "35s+ mastery challenge"],
        "feedback": ["clear hit flash", "score pop", "life/timer HUD", "restart affordance"],
        "keywords": keywords,
        "minimum_content": {"hazards": 2, "rewards": 3, "powerups": 2, "waves": 4},
    }


def _coerce_brief(data: dict, prompt: str, spec: dict) -> dict:
    base = _heuristic_brief(prompt, spec)
    if isinstance(data, dict):
        for key in ("player_fantasy", "objective", "reward_loop"):
            if data.get(key):
                base[key] = str(data[key])[:240]
        for key in ("core_verbs", "mechanic_requirements", "difficulty_beats", "feedback", "keywords"):
            if isinstance(data.get(key), list) and data[key]:
                base[key] = [str(item)[:80] for item in data[key]][:8]
        if isinstance(data.get("minimum_content"), dict):
            base["minimum_content"].update({k: int(v) for k, v in data["minimum_content"].items() if str(v).isdigit()})
    return base


def _brief_log_lines(brief: dict, source: str) -> list[str]:
    return [
        f"source: {source}",
        f"player fantasy: {_clip(brief.get('player_fantasy'), 120)}",
        f"objective: {_clip(brief.get('objective'), 120)}",
        "core verbs: " + ", ".join(brief.get("core_verbs") or []),
        "mechanic requirements: " + ", ".join(brief.get("mechanic_requirements") or []),
        "difficulty beats: " + " / ".join(brief.get("difficulty_beats") or []),
    ]


def _heuristic_mechanic_plan(spec: dict, brief: dict, prompt: str) -> dict:
    genre = str(spec.get("genre") or "").lower()
    text = " ".join([prompt, " ".join(brief.get("mechanic_requirements") or []), " ".join(brief.get("keywords") or [])]).lower()
    if genre == "shooter" or _has_any(text, ["shoot", "bullet", "shmup", "raiden", "战机", "雷霆", "射击", "弹幕", "飞机大战", "打飞机"]):
        archetype_hint = "vertical_shooter"
        secondary = "spread / laser power-ups and a screen-clearing bomb"
        enemies = [{"name": "swarm fighter", "behavior": "weaves downward firing aimed shots"}, {"name": "gunship", "behavior": "strafes the top and lays bullet spreads"}, {"name": "boss carrier", "behavior": "multi-phase, telegraphed barrages"}]
        rewards = [{"name": "power chip", "effect": "upgrades the main gun"}, {"name": "medal", "effect": "score chain"}]
        powerups = [{"name": "spread shot", "effect": "wider fire arc"}, {"name": "shield", "effect": "absorbs one hit"}, {"name": "wingman", "effect": "adds a side gun"}]
    elif genre == "puzzle" or _has_any(text, ["connect", "circuit", "puzzle", "logic"]):
        archetype_hint = "logic_grid"
        secondary = "route preview pulses"
        enemies = [{"name": "locked node", "behavior": "blocks inefficient routes"}, {"name": "timer drain", "behavior": "forces decisive rotations"}]
        rewards = [{"name": "clean link", "effect": "score bonus"}, {"name": "few moves", "effect": "efficiency bonus"}]
        powerups = [{"name": "hint pulse", "effect": "briefly shows connected tiles"}, {"name": "time crystal", "effect": "adds seconds"}]
    elif genre == "runner" or _has_any(text, ["runner", "lane", "dash", "dodge", "race"]):
        archetype_hint = "lane_runner"
        secondary = "one-lane dash recovery"
        enemies = [{"name": "drone gate", "behavior": "blocks one lane"}, {"name": "sweeper", "behavior": "encourages early lane change"}]
        rewards = [{"name": "energy orb", "effect": "score chain"}, {"name": "route badge", "effect": "lane streak bonus"}]
        powerups = [{"name": "phase dash", "effect": "forgive the next hit"}, {"name": "magnet trail", "effect": "pulls nearby bonuses"}]
    else:
        archetype_hint = "topdown_collect"
        secondary = "short shield after clean combo"
        enemies = [{"name": "drifter", "behavior": "soft-homes toward the player"}, {"name": "sentinel", "behavior": "crosses the arena slowly"}]
        rewards = [{"name": "glow shard", "effect": "combo score"}, {"name": "cache", "effect": "larger timed bonus"}]
        powerups = [{"name": "shield bloom", "effect": "temporary invulnerability"}, {"name": "slow field", "effect": "slows hazards"}, {"name": "spark dash", "effect": "quick reposition"}]
    return {
        "archetype_hint": archetype_hint,
        "primary_action": _clip((brief.get("core_verbs") or ["move"])[0], 60),
        "secondary_action": secondary,
        "risk_model": "mistakes cost lives, but the first seconds are safe and recovery is possible",
        "reward_model": brief.get("reward_loop") or "chain rewards for score",
        "enemy_behaviors": enemies,
        "reward_items": rewards,
        "powerups": powerups,
        "feedback": brief.get("feedback") or ["score pop", "hit flash", "restart"],
        "skill_tests": brief.get("difficulty_beats") or [],
    }


def _coerce_mechanic_plan(data: dict, spec: dict, brief: dict, prompt: str) -> dict:
    base = _heuristic_mechanic_plan(spec, brief, prompt)
    if isinstance(data, dict):
        for key in ("archetype_hint", "primary_action", "secondary_action", "risk_model", "reward_model"):
            if data.get(key):
                base[key] = str(data[key])[:180]
        for key in ("enemy_behaviors", "reward_items", "powerups"):
            if isinstance(data.get(key), list) and data[key]:
                base[key] = [item if isinstance(item, dict) else {"name": str(item), "effect": "gameplay variation"} for item in data[key]][:5]
        if isinstance(data.get("feedback"), list) and data["feedback"]:
            base["feedback"] = [str(item)[:80] for item in data["feedback"]][:6]
    if base.get("archetype_hint") not in _ARCHETYPES:
        base["archetype_hint"] = _heuristic_mechanic_plan(spec, brief, prompt)["archetype_hint"]
    return base


def _mechanic_log_lines(plan: dict, source: str) -> list[str]:
    enemies = ", ".join(str(item.get("name", "?")) for item in plan.get("enemy_behaviors") or [])
    rewards = ", ".join(str(item.get("name", "?")) for item in plan.get("reward_items") or [])
    powerups = ", ".join(str(item.get("name", "?")) for item in plan.get("powerups") or [])
    return [
        f"source: {source}",
        f"archetype hint: {plan.get('archetype_hint')}",
        f"primary/secondary: {plan.get('primary_action')} / {plan.get('secondary_action')}",
        f"risk model: {_clip(plan.get('risk_model'), 120)}",
        f"reward model: {_clip(plan.get('reward_model'), 120)}",
        f"enemy behaviors: {enemies}",
        f"rewards/powerups: {rewards} / {powerups}",
    ]


def _content_plan(archetype: str, spec: dict, brief: dict, mechanics: dict) -> dict:
    enemy_names = [str(item.get("name", "hazard"))[:28] for item in mechanics.get("enemy_behaviors") or []] or ["hazard", "blocker"]
    reward_names = [str(item.get("name", "reward"))[:28] for item in mechanics.get("reward_items") or []] or ["reward", "bonus"]
    powerups = [str(item.get("name", "boost"))[:28] for item in mechanics.get("powerups") or []] or ["shield", "slow field"]
    beats = brief.get("difficulty_beats") or ["opening", "pressure", "mastery"]
    if archetype == "logic_grid":
        waves = [
            {"time": 0, "pressure": "learn", "note": beats[0]},
            {"time": 18, "pressure": "optimize", "note": beats[min(1, len(beats) - 1)]},
            {"time": 40, "pressure": "rush", "note": beats[-1]},
        ]
        tutorial = "click tiles to rotate the live route from IN to OUT"
    elif archetype == "lane_runner":
        waves = [
            {"time": 0, "hazards": 1, "reward": 1, "note": beats[0]},
            {"time": 12, "hazards": 2, "reward": 1, "note": beats[min(1, len(beats) - 1)]},
            {"time": 28, "hazards": 3, "reward": 2, "note": "introduce paired lane reads"},
            {"time": 45, "hazards": 4, "reward": 2, "note": beats[-1]},
        ]
        tutorial = "tap left or right to switch lanes; chase bonuses, not every gap"
    else:
        waves = [
            {"time": 0, "hazards": 1, "reward": 2, "note": beats[0]},
            {"time": 14, "hazards": 2, "reward": 2, "note": beats[min(1, len(beats) - 1)]},
            {"time": 32, "hazards": 3, "reward": 3, "note": "use powerups to reset danger"},
            {"time": 50, "hazards": 4, "reward": 3, "note": beats[-1]},
        ]
        tutorial = "move smoothly, collect chains, use powerups when the arena tightens"
    return {
        "tutorial": tutorial,
        "waves": waves,
        "hazard_names": enemy_names[:4],
        "reward_names": reward_names[:4],
        "powerups": powerups[:4],
        "pacing": beats,
        "mechanic_label": mechanics.get("secondary_action") or mechanics.get("primary_action") or "core loop",
    }


def _content_log_lines(plan: dict) -> list[str]:
    return [
        f"tutorial: {_clip(plan.get('tutorial'), 120)}",
        "waves: " + "; ".join(f"{w.get('time')}s {w.get('note')}" for w in plan.get("waves", [])[:5]),
        "hazards: " + ", ".join(plan.get("hazard_names") or []),
        "rewards: " + ", ".join(plan.get("reward_names") or []),
        "powerups: " + ", ".join(plan.get("powerups") or []),
        f"mechanic label: {plan.get('mechanic_label')}",
    ]


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


def _balance_log_lines(archetype: str, balance: dict) -> list[str]:
    qa = balance.get("qa") if isinstance(balance.get("qa"), dict) else {}
    return [
        f"selected playable archetype: {archetype}",
        f"round target: {balance.get('target_score')} points in {balance.get('round_seconds')}s",
        f"player/hazard: speed={balance.get('player_speed')} / {balance.get('hazard_speed')}, lives={balance.get('lives')}",
        f"spawn budget: hazard every {balance.get('hazard_spawn_ms')}ms, collectible every {balance.get('collectible_spawn_ms')}ms, max hazards={balance.get('max_hazards')}",
        "QA thresholds: " + (", ".join(f"{key}={value}" for key, value in qa.items()) or "default"),
    ]


def safety_intake_node(state: dict) -> dict:
    prompt = state.get("prompt", "") or ""
    if not prompt.strip():
        return {
            "status": "failed",
            "error_code": TaskErrorCode.VALIDATION_FAILED.value,
            "error_message": "Prompt cannot be empty",
            "_agent": "SafetyIntakeAgent",
            "_logs": ["prompt is empty -> rejected"],
        }
    if len(prompt) > 2000:
        return {
            "status": "failed",
            "error_code": TaskErrorCode.PROMPT_TOO_LONG.value,
            "error_message": "Prompt too long (>2000 chars)",
            "_agent": "SafetyIntakeAgent",
            "_logs": ["prompt exceeds 2000 chars -> rejected"],
        }
    moderation_log = "moderation skipped: unable to persist event"
    moderation_unavailable = None
    try:
        from app.db.session import SessionLocal

        db = SessionLocal()
        try:
            decision = content_safety.moderate_and_record(
                db,
                text=prompt,
                surface=(
                    "task.idea"
                    if state.get("task_kind") == "generation"
                    else "task.remix_prompt"
                    if state.get("task_kind") == "remix"
                    else "task.revision_feedback"
                ),
                user_id=state.get("user_id"),
                object_id=state.get("task_id"),
            )
            if decision.errored and content_safety.should_enforce():
                moderation_unavailable = ("prompt", "", decision)
            asset_blocked = None
            asset_ids = state.get("asset_ids") or []
            if asset_ids and not moderation_unavailable:
                from app.models import Asset

                for asset in db.query(Asset).filter(Asset.id.in_(asset_ids)).all():
                    asset_decision = content_safety.moderate_and_record(
                        db,
                        text=asset.filename,
                        surface="asset.filename",
                        user_id=state.get("user_id"),
                        object_id=asset.id,
                    )
                    if asset_decision.blocked:
                        asset_blocked = (asset.filename, asset_decision)
                        break
                    if asset_decision.errored and content_safety.should_enforce():
                        moderation_unavailable = ("asset", asset.filename, asset_decision)
                        break
            db.commit()
        finally:
            db.close()
        categories = ", ".join(decision.categories.keys()) or "none"
        moderation_log = f"moderation: {decision.provider}/{decision.action}, categories={categories}"
        if decision.blocked:
            return {
                "status": "failed",
                "error_code": TaskErrorCode.MODERATION_BLOCKED.value,
                "error_message": "Prompt rejected by content moderation",
                "_agent": "SafetyIntakeAgent",
                "_logs": [moderation_log, "prompt blocked before generation"],
            }
        if asset_blocked:
            filename, asset_decision = asset_blocked
            asset_categories = ", ".join(asset_decision.categories.keys()) or "none"
            return {
                "status": "failed",
                "error_code": TaskErrorCode.MODERATION_BLOCKED.value,
                "error_message": "Uploaded asset filename rejected by content moderation",
                "_agent": "SafetyIntakeAgent",
                "_logs": [
                    moderation_log,
                    f"asset filename blocked: {_clip(filename, 80)} categories={asset_categories}",
                ],
            }
        if moderation_unavailable:
            scope, filename, failure_decision = moderation_unavailable
            failure_categories = ", ".join(failure_decision.categories.keys()) or "none"
            target = "prompt" if scope == "prompt" else f"asset filename: {_clip(filename, 80)}"
            return {
                "status": "failed",
                "error_code": TaskErrorCode.SAFETY_REJECTED.value,
                "error_message": "Content moderation is unavailable",
                "_agent": "SafetyIntakeAgent",
                "_logs": [
                    moderation_log,
                    f"moderation unavailable for {target}; categories={failure_categories}",
                    "generation stopped because moderation could not verify the input",
                ],
            }
    except Exception as exc:  # noqa: BLE001
        moderation_log = f"moderation failed: {_clip(exc, 120)}"
        if content_safety.should_enforce():
            return {
                "status": "failed",
                "error_code": TaskErrorCode.SAFETY_REJECTED.value,
                "error_message": "Content moderation is unavailable",
                "_agent": "SafetyIntakeAgent",
                "_logs": [
                    moderation_log,
                    "generation stopped because moderation could not verify the input",
                ],
            }
    cues = _prompt_cues(prompt)
    return {
        "normalized_prompt": prompt.strip(),
        "safety_result": {"passed": True, "risk_level": "low"},
        "_agent": "SafetyIntakeAgent",
        "_logs": [
            f"prompt accepted: {len(prompt)} chars, {len(prompt.split())} word(s)",
            "intent cues: " + (", ".join(cues) if cues else "none detected"),
            f"uploaded asset ids received: {len(state.get('asset_ids') or [])}",
            moderation_log,
            f"policy scan passed: {len(content_safety.BLOCKLIST_PATTERNS)} blocked-pattern checks",
            f"normalized prompt: {_clip(prompt, 160)}",
        ],
    }


def intent_spec_node(state: dict) -> dict:
    prompt = state.get("normalized_prompt") or state.get("prompt", "")
    if state.get("use_real"):
        try:
            raw, tokens = llm.chat(
                prompts.INTENT_SPEC_SYSTEM_PROMPT,
                prompts.build_intent_spec_prompt(
                    prompt,
                    len(state.get("asset_ids") or []),
                    state.get("memory_context") or "",
                ),
            )
            spec = _coerce_spec(_parse_json(raw), prompt)
            return {"game_spec": spec, "_agent": "IntentSpecAgent", "_tokens_delta": tokens, "_logs": _spec_log_lines(spec, "model GameSpec JSON")}
        except Exception as exc:  # noqa: BLE001
            _real_model_fallback_or_raise("IntentSpecAgent", exc, exc)
            spec = _heuristic_spec(prompt)
            return {"game_spec": spec, "_agent": "IntentSpecAgent", "_logs": [f"model failed: {_clip(exc, 120)}"] + _spec_log_lines(spec, "heuristic fallback")}
    spec = _heuristic_spec(prompt)
    return {"game_spec": spec, "_agent": "IntentSpecAgent", "_logs": _spec_log_lines(spec, "offline heuristic")}


def brief_expansion_node(state: dict) -> dict:
    prompt = state.get("normalized_prompt") or state.get("prompt", "")
    spec = state.get("game_spec") or {}
    if state.get("use_real"):
        try:
            raw, tokens = llm.chat(
                "Expand a short game prompt into compact JSON for a playable browser mini-game. Do not add unsafe APIs.",
                (
                    "Return JSON with keys player_fantasy, objective, core_verbs, mechanic_requirements, "
                    "reward_loop, difficulty_beats, feedback, keywords, minimum_content. "
                    f"Prompt: {prompt}\nSpec: {json.dumps(spec, ensure_ascii=False)}"
                ),
            )
            brief = _coerce_brief(_parse_json(raw), prompt, spec)
            return {"expanded_brief": brief, "_agent": "BriefExpansionAgent", "_tokens_delta": tokens, "_logs": _brief_log_lines(brief, "model brief expansion")}
        except Exception as exc:  # noqa: BLE001
            _real_model_fallback_or_raise("BriefExpansionAgent", exc, exc)
            brief = _heuristic_brief(prompt, spec)
            return {"expanded_brief": brief, "_agent": "BriefExpansionAgent", "_logs": [f"model failed: {_clip(exc, 120)}"] + _brief_log_lines(brief, "heuristic fallback")}
    brief = _heuristic_brief(prompt, spec)
    return {"expanded_brief": brief, "_agent": "BriefExpansionAgent", "_logs": _brief_log_lines(brief, "offline heuristic")}


def mechanic_planner_node(state: dict) -> dict:
    prompt = state.get("normalized_prompt") or state.get("prompt", "")
    spec = state.get("game_spec") or {}
    brief = state.get("expanded_brief") or _heuristic_brief(prompt, spec)
    if state.get("use_real"):
        try:
            raw, tokens = llm.chat(
                "Plan concrete mini-game mechanics as bounded JSON. Prefer proven mechanics over novelty.",
                (
                    "Return JSON with keys archetype_hint, primary_action, secondary_action, risk_model, reward_model, "
                    "enemy_behaviors, reward_items, powerups, feedback, skill_tests. "
                    f"Spec: {json.dumps(spec, ensure_ascii=False)}\nBrief: {json.dumps(brief, ensure_ascii=False)}"
                ),
            )
            plan = _coerce_mechanic_plan(_parse_json(raw), spec, brief, prompt)
            return {"mechanic_plan": plan, "_agent": "MechanicPlannerAgent", "_tokens_delta": tokens, "_logs": _mechanic_log_lines(plan, "model mechanic plan")}
        except Exception as exc:  # noqa: BLE001
            _real_model_fallback_or_raise("MechanicPlannerAgent", exc, exc)
            plan = _heuristic_mechanic_plan(spec, brief, prompt)
            return {"mechanic_plan": plan, "_agent": "MechanicPlannerAgent", "_logs": [f"model failed: {_clip(exc, 120)}"] + _mechanic_log_lines(plan, "heuristic fallback")}
    plan = _heuristic_mechanic_plan(spec, brief, prompt)
    return {"mechanic_plan": plan, "_agent": "MechanicPlannerAgent", "_logs": _mechanic_log_lines(plan, "offline heuristic")}


def archetype_router_node(state: dict) -> dict:
    prompt = state.get("normalized_prompt") or state.get("prompt", "")
    spec = dict(state.get("game_spec") or {})
    is_3d = state.get("dimension") == "3d"
    if is_3d:
        spec["dimension"] = "3d"
        spec["target_runtime"] = "webgl"
        result = _route_archetype_3d(spec, prompt, state.get("expanded_brief"), state.get("mechanic_plan"))
    else:
        spec["dimension"] = "2d"
        result = _route_archetype(spec, prompt, state.get("expanded_brief"), state.get("mechanic_plan"))
    spec["archetype"] = result["archetype"]
    spec["genre"] = result["genre"]
    spec["core_loop"] = result["core_loop"]
    tags = [str(tag) for tag in (spec.get("tags") or [])]
    for tag in [result["genre"], result["archetype"].replace("_", "-")]:
        if tag not in tags:
            tags.append(tag)
    spec["tags"] = tags[:5]
    return {
        "game_spec": spec,
        "archetype_result": result,
        "_agent": "ArchetypeRouterAgent",
        "_logs": [
            f"archetype selected: {result['archetype']} ({result['label']})",
            f"routing reason: {result['reason']}",
            f"core loop locked: {result['core_loop']}",
            (
                "runtime: 3D WebGL (Three.js, self-hosted) — model-authored, no template fallback"
                if is_3d
                else "template family: deterministic canvas, no network, no storage"
            ),
        ],
    }


def asset_processing_node(state: dict) -> dict:
    from app.db.session import SessionLocal
    from app.models import Asset
    from app.services.upload_safety import presigned_asset_url

    ids = state.get("asset_ids") or []
    uploaded = []
    if ids:
        db = SessionLocal()
        try:
            for asset in db.query(Asset).filter(Asset.id.in_(ids)).all():
                url = presigned_asset_url(asset)
                if url:
                    uploaded.append({"id": asset.id, "key": asset.filename, "type": asset.kind, "url": url, "source": "uploaded"})
        finally:
            db.close()
    spec = state.get("game_spec") or {}
    asset_manifest = {"cover": _theme_cover(spec.get("theme")), "assets": uploaded}
    return {"uploaded_assets": uploaded, "asset_manifest": asset_manifest, "_agent": "AssetAgent", "_logs": _asset_log_lines(uploaded, asset_manifest, spec)}


def game_design_node(state: dict) -> dict:
    spec = state.get("game_spec") or {}
    is_3d = state.get("dimension") == "3d"
    if state.get("use_real"):
        try:
            sys_prompt = prompts.GAME_DESIGN_SYSTEM_PROMPT_3D if is_3d else prompts.GAME_DESIGN_SYSTEM_PROMPT
            raw, tokens = llm.chat(sys_prompt, prompts.build_game_design_prompt(
                spec,
                state.get("asset_manifest"),
                expanded_brief=state.get("expanded_brief"),
                mechanic_plan=state.get("mechanic_plan"),
                player_idea=state.get("normalized_prompt") or state.get("prompt"),
                memory_context=state.get("memory_context") or "",
            ))
            design = _coerce_design(_parse_json(raw), spec)
            fed = [k for k, v in (("brief", state.get("expanded_brief")), ("mechanic_plan", state.get("mechanic_plan")), ("player_idea", state.get("normalized_prompt"))) if v]
            out = {"game_design": design, "_agent": "GameDesignAgent", "_tokens_delta": tokens,
                   "_logs": [f"source: model GameDesign JSON ({'3D' if is_3d else '2D'})",
                             "design context fed: " + (", ".join(fed) or "spec only")] + _design_log_lines(design)}
            if is_3d:
                new_arch = _reconcile_archetype_3d(spec, design)
                if new_arch != spec.get("archetype"):
                    meta = _ARCHETYPES_3D[new_arch]
                    out["game_spec"] = {**spec, "archetype": new_arch, "genre": meta["genre"], "core_loop": meta["loop"]}
                    out["_logs"].append(f"3D archetype reconciled from design camera -> {new_arch}")
            return out
        except Exception as exc:  # noqa: BLE001
            _real_model_fallback_or_raise("GameDesignAgent", exc, exc)
            design = _heuristic_design(spec)
            return {"game_design": design, "_agent": "GameDesignAgent", "_logs": [f"model failed: {_clip(exc, 120)}", "source: heuristic fallback"] + _design_log_lines(design)}
    design = _heuristic_design(spec)
    return {"game_design": design, "_agent": "GameDesignAgent", "_logs": ["source: offline heuristic"] + _design_log_lines(design)}


def content_plan_node(state: dict) -> dict:
    spec = state.get("game_spec") or {}
    brief = state.get("expanded_brief") or _heuristic_brief(state.get("normalized_prompt") or state.get("prompt", ""), spec)
    mechanics = state.get("mechanic_plan") or _heuristic_mechanic_plan(spec, brief, state.get("normalized_prompt") or state.get("prompt", ""))
    archetype = spec.get("archetype") or (state.get("archetype_result") or {}).get("archetype") or mechanics.get("archetype_hint") or "topdown_collect"
    plan = _content_plan(archetype, spec, brief, mechanics)
    design = dict(state.get("game_design") or _heuristic_design(spec))
    design["mechanic_plan"] = mechanics
    design["content_plan"] = plan
    return {
        "game_design": design,
        "content_plan": plan,
        "_agent": "ContentPlanAgent",
        "_logs": _content_log_lines(plan),
    }


def balance_plan_node(state: dict) -> dict:
    prompt = state.get("normalized_prompt") or state.get("prompt", "")
    spec = dict(state.get("game_spec") or {})
    archetype = spec.get("archetype") or (state.get("archetype_result") or {}).get("archetype") or "topdown_collect"
    balance = _balance_plan(archetype, spec, prompt)
    design = _merge_balance_into_design(state.get("game_design") or _heuristic_design(spec), archetype, balance)
    if state.get("mechanic_plan"):
        design["mechanic_plan"] = state["mechanic_plan"]
    if state.get("content_plan"):
        design["content_plan"] = state["content_plan"]
    return {
        "game_spec": spec,
        "game_design": design,
        "balance_config": balance,
        "_agent": "BalanceAgent",
        "_logs": _balance_log_lines(archetype, balance),
    }


def feedback_understanding_node(state: dict) -> dict:
    feedback = state.get("source_feedback") or state.get("prompt") or ""
    tokens = 0
    if state.get("use_real"):
        try:
            brief, tokens = llm.chat(
                prompts.FEEDBACK_UNDERSTANDING_SYSTEM_PROMPT,
                prompts.build_feedback_understanding_prompt(
                    feedback,
                    state.get("game_spec") or {},
                    state.get("game_design") or {},
                    state.get("memory_context") or "",
                ),
            )
        except Exception as exc:  # noqa: BLE001
            _real_model_fallback_or_raise("FeedbackUnderstandingAgent", exc, exc)
            brief = f"Change goal\n{feedback}\n\nPreserve\nAll behavior not mentioned by the player.\n\nUncertainties\nModel interpretation failed: {_clip(exc, 120)}"
    else:
        brief = f"Change goal\n{feedback}\n\nPreserve\nAll behavior not mentioned by the player.\n\nUncertainties\nNone inferred in offline mode."
    return {
        "feedback_brief": brief,
        "_agent": "FeedbackUnderstandingAgent",
        "_tokens_delta": tokens,
        "_logs": [
            f"preserved raw feedback: {_clip(feedback, 180)}",
            f"natural-language change brief: {_clip(brief, 240)}",
        ],
    }


def failed_node(state: dict) -> dict:
    msg = state.get("error_message") or state.get("last_error") or "generation failed"
    return {
        "status": "failed",
        "error_message": msg,
        "error_code": state.get("error_code") or TaskErrorCode.UNKNOWN.value,
        "_agent": "FailureHandler",
        "_logs": [
            f"task failed: {_clip(msg, 220)}",
            f"repair attempts used: {state.get('repair_attempts', 0)}/{MAX_REPAIR}",
            f"gameplay repair attempts used: {state.get('gameplay_repair_attempts', 0)}/{MAX_GAMEPLAY_REPAIR}",
            f"replan attempts used: {state.get('replan_attempts', 0)}/{MAX_REPLAN}",
        ],
    }


def done_node(state: dict) -> dict:
    return {
        "status": "succeeded",
        "_agent": "DoneHandler",
        "_logs": [f"generation succeeded for game_id={state.get('game_id', 'unknown')}", f"preview url: {state.get('preview_url', 'pending')}"],
    }


def should_continue_after_safety(state: dict) -> str:
    if state.get("status") == "failed":
        return "failed"
    return "memory_retrieval"


def entry_node_router(state: dict) -> str:
    # 断点续跑入口：pipeline 从 state_json 快照恢复时注入 _resume_node，直接跳到
    # 失败节点重跑（同一任务行输入不可变，原次 safety_result 已在快照里，安检
    # 结论仍然有效）；正常任务照旧从 safety_intake 全链路开始。未知节点名一律
    # 回落全新跑，绝不比旧路径更差。
    node = state.get("_resume_node")
    return node if node in STEP_META else "safety_intake"


__all__ = [
    '_detect_theme',
    '_detect_genre',
    '_theme_cover',
    '_heuristic_spec',
    '_coerce_spec',
    '_heuristic_design',
    '_coerce_design',
    '_simplify_design',
    '_simplify_design_3d',
    '_prompt_cues',
    '_controls_line',
    '_spec_log_lines',
    '_entity_line',
    '_design_log_lines',
    '_asset_log_lines',
    '_brief_keywords',
    '_heuristic_brief',
    '_coerce_brief',
    '_brief_log_lines',
    '_heuristic_mechanic_plan',
    '_coerce_mechanic_plan',
    '_mechanic_log_lines',
    '_content_plan',
    '_content_log_lines',
    '_route_archetype',
    '_route_archetype_3d',
    '_reconcile_archetype_3d',
    '_difficulty_factor',
    '_balance_plan',
    '_merge_balance_into_design',
    '_balance_log_lines',
    'safety_intake_node',
    'intent_spec_node',
    'brief_expansion_node',
    'mechanic_planner_node',
    'archetype_router_node',
    'asset_processing_node',
    'game_design_node',
    'content_plan_node',
    'balance_plan_node',
    'feedback_understanding_node',
    'failed_node',
    'done_node',
    'should_continue_after_safety',
    'entry_node_router',
]
