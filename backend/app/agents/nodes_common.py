"""Shared imports, constants, and helpers for LangGraph node modules."""
import json
import re

from app.agents import bundles, code_agent, llm, prompts, smoke, validation
from app.agents.state import MAX_GAMEPLAY_REPAIR, MAX_REPAIR, MAX_REPLAN, STEP_META
from app.core.config import settings
from app.core.errors import TaskErrorCode
from app.services import content_safety, sandbox_client
from app.services.artifacts import artifact_size
from app.storage import s3


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


def _real_model_fallback_or_raise(stage: str, detail: object, exc: Exception | None = None) -> None:
    if settings.REAL_MODEL_FALLBACK_ENABLED:
        return
    message = f"{stage} real model failed; fallback disabled: {_clip(detail, 300)}"
    if exc is not None:
        raise RuntimeError(message) from exc
    raise RuntimeError(message)


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


def _file_log_lines(files: list[dict]) -> list[str]:
    if not files:
        return ["generated files: none"]
    total = sum(artifact_size(file) for file in files)
    names = ", ".join(file.get("path", "?") for file in files)
    lines = [f"{file.get('path', '?')}: {artifact_size(file)} bytes" for file in files]
    lines.append(f"bundle size: {total} bytes")
    # 摘要行放最后：task_out 取步骤末行当 step summary，前端进度页直接显示文件结构
    lines.append(f"generated files: {names} ({len(files)} file(s))")
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


__all__ = [
    'json',
    're',
    'bundles',
    'code_agent',
    'llm',
    'prompts',
    'smoke',
    'validation',
    'MAX_GAMEPLAY_REPAIR',
    'MAX_REPAIR',
    'MAX_REPLAN',
    'STEP_META',
    'settings',
    'TaskErrorCode',
    'content_safety',
    'sandbox_client',
    's3',
    '_THEMES',
    '_THEME_COVER',
    '_ARCHETYPES',
    '_ARCHETYPES_3D',
    '_real_model_fallback_or_raise',
    '_parse_json',
    '_clip',
    '_has_any',
    '_file_log_lines',
    '_validation_log_lines',
]
