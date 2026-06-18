"""GameCode 的模板渲染（docs/multi-agent_design.md §6.5）。

LLM 负责产出 GameSpec / GameDesign（创意与玩法），最终代码由固定模板 + config 渲染，
保证产物结构固定、可校验、无外联——这是 MVP 的安全与稳定取舍。
新增玩法只需加一个 game_templates/<name>/ 目录并在 GENRE_TEMPLATE 注册。
"""
import os

from jinja2 import Environment, FileSystemLoader

# backend/app/agents/templating.py -> 上溯 3 层到 backend/，再进 game_templates/
_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "game_templates")
_env = Environment(loader=FileSystemLoader(_ROOT), autoescape=False, keep_trailing_newline=True)

DEFAULT_TEMPLATE = "canvas_arcade"
GENRE_TEMPLATE = {
    "arcade": "canvas_arcade",
    "runner": "canvas_arcade",
    "shooter": "canvas_arcade",
    "puzzle": "canvas_arcade",
    "quiz": "canvas_arcade",
}

_ACCENT_BY_THEME = {
    "space": "#22d3ee", "neon": "#7c5cff", "candy": "#ff3ea5",
    "forest": "#39ff88", "retro": "#ff6b35", "ocean": "#0ea5b7",
}
_FILES = ("index.html", "style.css", "game.js")


def select_template(game_spec: dict, game_design: dict) -> str:
    return GENRE_TEMPLATE.get((game_spec or {}).get("genre"), DEFAULT_TEMPLATE)


def build_config(game_spec: dict, game_design: dict, asset_manifest: dict) -> dict:
    spec = game_spec or {}
    design = game_design or {}
    theme = str(spec.get("theme", "")).lower()
    accent = next((v for k, v in _ACCENT_BY_THEME.items() if k in theme), "#ff6b35")

    rules = design.get("rules") if isinstance(design.get("rules"), dict) else {}
    duration = rules.get("survive_seconds") or rules.get("survive") or 45
    try:
        duration = max(20, min(90, int(duration)))
    except (TypeError, ValueError):
        duration = 45

    diff = str(spec.get("difficulty_curve", "")).lower()
    hazard_speed = 3.0 if "fast" in diff or "hard" in diff else 2.3

    controls = spec.get("controls") if isinstance(spec.get("controls"), dict) else {}
    hint = controls.get("hint") or "move the mouse / arrow keys — dodge red, catch the stars"

    return {
        "title": str(spec.get("title") or "Untitled Game")[:60],
        "accent": accent,
        "hazard_speed": hazard_speed,
        "star_speed": 2.0,
        "duration": duration,
        "hint": str(hint)[:80],
    }


def render_files(template_name: str, config: dict) -> list[dict]:
    files = []
    for path in _FILES:
        tmpl = _env.get_template(f"{template_name}/{path}.j2")
        files.append({"path": path, "content": tmpl.render(**config)})
    return files
