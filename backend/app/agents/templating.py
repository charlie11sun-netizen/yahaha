"""Deterministic game template renderer.

The model plans GameSpec/GameDesign. Code generation renders a fixed local
template with bounded config so artifacts stay validateable and sandbox-safe.
"""
import os
import json

from jinja2 import Environment, FileSystemLoader

_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "game_templates")
_env = Environment(loader=FileSystemLoader(_ROOT), autoescape=False, keep_trailing_newline=True)

DEFAULT_TEMPLATE = "canvas_arcade"
GENRE_TEMPLATE = {
    "arcade": "canvas_arcade",
    "runner": "lane_runner",
    "shooter": "canvas_arcade",
    "puzzle": "logic_grid",
    "quiz": "canvas_arcade",
}
ARCHETYPE_TEMPLATE = {
    "lane_runner": "lane_runner",
    "topdown_collect": "topdown_collect",
    "logic_grid": "logic_grid",
    "canvas_arcade": "canvas_arcade",
}

_ACCENT_BY_THEME = {
    "space": "#22d3ee",
    "neon": "#7c5cff",
    "candy": "#ff3ea5",
    "forest": "#39ff88",
    "retro": "#ff6b35",
    "ocean": "#0ea5b7",
}
_FILES = ("index.html", "style.css", "game.js")


def select_template(game_spec: dict, game_design: dict) -> str:
    spec = game_spec or {}
    design = game_design or {}
    archetype = spec.get("archetype") or design.get("archetype")
    if archetype in ARCHETYPE_TEMPLATE:
        return ARCHETYPE_TEMPLATE[archetype]
    return GENRE_TEMPLATE.get(str(spec.get("genre") or "").lower(), DEFAULT_TEMPLATE)


def _number(value, default, lo, hi):
    try:
        return max(lo, min(hi, float(value)))
    except (TypeError, ValueError):
        return default


def _integer(value, default, lo, hi):
    return int(_number(value, default, lo, hi))


def build_config(game_spec: dict, game_design: dict, asset_manifest: dict, balance_config: dict | None = None) -> dict:
    spec = game_spec or {}
    design = game_design or {}
    balance = balance_config or (design.get("balance") if isinstance(design.get("balance"), dict) else {}) or {}
    mechanics = design.get("mechanic_plan") if isinstance(design.get("mechanic_plan"), dict) else {}
    content = design.get("content_plan") if isinstance(design.get("content_plan"), dict) else {}
    theme = str(spec.get("theme", "")).lower()
    accent = next((v for k, v in _ACCENT_BY_THEME.items() if k in theme), "#ff6b35")

    rules = design.get("rules") if isinstance(design.get("rules"), dict) else {}
    duration = balance.get("round_seconds") or rules.get("survive_seconds") or rules.get("survive") or 45
    duration = _integer(duration, 45, 20, 90)

    diff = str(spec.get("difficulty_curve", "")).lower()
    hazard_speed = balance.get("hazard_speed")
    if hazard_speed is None:
        hazard_speed = 3.0 if "fast" in diff or "hard" in diff else 2.3
    hazard_speed = _number(hazard_speed, 2.3, 0.5, 360.0)

    controls = spec.get("controls") if isinstance(spec.get("controls"), dict) else {}
    hint = controls.get("hint") or "move with mouse / arrows, collect rewards, avoid hazards"

    return {
        "title": str(spec.get("title") or "Untitled Game")[:60],
        "accent": accent,
        "hazard_speed": hazard_speed,
        "star_speed": _number(balance.get("collectible_speed"), 2.0, 0.4, 240.0),
        "player_speed": _number(balance.get("player_speed"), 280, 120, 620),
        "hazard_spawn_ms": _integer(balance.get("hazard_spawn_ms"), 1250, 500, 4000),
        "collectible_spawn_ms": _integer(balance.get("collectible_spawn_ms"), 900, 300, 4000),
        "max_hazards": _integer(balance.get("max_hazards"), 8, 2, 24),
        "target_score": _integer(balance.get("target_score"), 180, 20, 9999),
        "lives": _integer(balance.get("lives"), 3, 1, 9),
        "lanes": _integer(balance.get("lanes"), 3, 3, 5),
        "archetype": str(spec.get("archetype") or design.get("archetype") or DEFAULT_TEMPLATE),
        "mechanic_label": str(content.get("mechanic_label") or mechanics.get("secondary_action") or mechanics.get("primary_action") or "core loop")[:80],
        "tutorial_json": json.dumps(str(content.get("tutorial") or hint)[:140], ensure_ascii=False),
        "hazard_names_json": json.dumps([str(item)[:32] for item in (content.get("hazard_names") or ["hazard"])][:5], ensure_ascii=False),
        "reward_names_json": json.dumps([str(item)[:32] for item in (content.get("reward_names") or ["reward"])][:5], ensure_ascii=False),
        "powerup_names_json": json.dumps([str(item)[:32] for item in (content.get("powerups") or ["shield", "slow field"])][:5], ensure_ascii=False),
        "wave_script_json": json.dumps(content.get("waves") or [], ensure_ascii=False),
        "wave_count": len(content.get("waves") or []),
        "duration": duration,
        "hint": str(hint)[:100],
    }


def _template_ref(template_name: str, path: str) -> str:
    preferred = f"{template_name}/{path}.j2"
    if os.path.exists(os.path.join(_ROOT, preferred)):
        return preferred
    return f"{DEFAULT_TEMPLATE}/{path}.j2"


def render_files(template_name: str, config: dict) -> list[dict]:
    files = []
    for path in _FILES:
        tmpl = _env.get_template(_template_ref(template_name, path))
        files.append({"path": path, "content": tmpl.render(**config)})
    return files
