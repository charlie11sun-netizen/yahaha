"""Screenshot-based visual quality review for gameplay QA.

Two layers, both fail-open (a review failure never blocks a task):
1. A deterministic blank-screen probe (PIL) — catches "the loop runs but draws
   nothing", which frame counting alone cannot see.
2. A VLM review of the after-input screenshot — the only signal in the pipeline
   that can judge aesthetics/readability the way a player would.
"""
from __future__ import annotations

import base64
import io
import json
import logging

from app.agents import llm
from app.core.config import settings

logger = logging.getLogger(__name__)

# Below this many distinct colors (on a downsampled frame) the screen is a flat
# fill or a bare gradient — not a composed game scene.
_BLANK_DISTINCT_COLORS = 8
_BLANK_STDDEV = 6.0

_REVIEW_SYSTEM = """You are a strict but fair art director reviewing ONE gameplay screenshot of a small browser game (embedded at roughly 840x470). Judge only what is visible.

Return only a JSON object:
{"aesthetic_score": 0-5, "readability_score": 0-5, "looks_like_placeholder": bool, "blank_or_broken": bool, "top_issues": ["..."], "strengths": ["..."]}

Scoring anchors:
- aesthetic_score: 0-1 broken/empty or raw untextured primitives only; 2 functional but visually flat (no palette identity, no lighting/contrast hierarchy); 3 coherent style with readable hierarchy; 4 polished (layered background, consistent palette, visible feedback effects); 5 shippable arcade quality.
- readability_score: 0-1 essential state unreadable or missing HUD; 2 cramped/low-contrast or overlapping text; 3+ the player can read state at a glance.
- looks_like_placeholder: true when the scene is mostly bare colored rectangles/circles with no art direction, or an obviously unfinished stage.
- blank_or_broken: true for an essentially empty/black/white frame, a missing-texture checkerboard, or garbled rendering.
- top_issues: at most 4 short, concrete, fixable observations (e.g. "HUD text overlaps the score", "player sprite floats above the platform shadowless"), most severe first.
- strengths: at most 2, only if genuinely present.

The screenshot may show a title screen if the game did not advance; judge that screen on the same scale but mention it in top_issues."""


def blank_screen_reason(png_b64: str) -> str | None:
    """Deterministic probe: returns a reason string when the frame is essentially blank."""
    try:
        from PIL import Image, ImageStat

        raw = base64.b64decode(png_b64, validate=False)
        image = Image.open(io.BytesIO(raw)).convert("RGB")
        probe = image.resize((64, 36))
        colors = probe.getcolors(64 * 36) or []
        stddev = max(ImageStat.Stat(probe).stddev)
        if len(colors) <= _BLANK_DISTINCT_COLORS and stddev <= _BLANK_STDDEV:
            return (
                f"frame is essentially uniform ({len(colors)} distinct colors, "
                f"stddev {stddev:.1f})"
            )
        return None
    except Exception:  # noqa: BLE001 - probe must never block QA
        logger.exception("blank-screen probe failed")
        return None


def review_screenshot(png_b64: str, spec: dict, design: dict) -> dict | None:
    """VLM review of the gameplay screenshot. Returns the parsed verdict or None."""
    if not settings.VISUAL_REVIEW_ENABLED:
        return None
    context = {
        "title": spec.get("title"),
        "genre": spec.get("genre"),
        "theme": spec.get("theme"),
        "visual_style": spec.get("visual_style"),
        "palette": (design.get("design") or {}).get("palette") or design.get("palette"),
    }
    prompt = (
        "Game context (for intent only, judge the pixels):\n"
        + json.dumps({k: v for k, v in context.items() if v}, ensure_ascii=False)[:800]
    )
    try:
        result = llm.chat(
            _REVIEW_SYSTEM,
            prompt,
            model=settings.VISUAL_REVIEW_MODEL or None,
            timeout=settings.VISUAL_REVIEW_TIMEOUT_SECONDS,
            response_format={"type": "json_object"},
            images_b64=[png_b64],
        )
        verdict = json.loads(result.text)
    except Exception as exc:  # noqa: BLE001 - fail-open soft gate
        logger.warning("visual review unavailable: %s", str(exc)[:200])
        return None
    if not isinstance(verdict, dict):
        return None
    return {
        "aesthetic_score": _clamp_score(verdict.get("aesthetic_score")),
        "readability_score": _clamp_score(verdict.get("readability_score")),
        "looks_like_placeholder": bool(verdict.get("looks_like_placeholder")),
        "blank_or_broken": bool(verdict.get("blank_or_broken")),
        "top_issues": [
            str(item)[:200] for item in (verdict.get("top_issues") or [])[:4]
        ],
        "strengths": [
            str(item)[:200] for item in (verdict.get("strengths") or [])[:2]
        ],
    }


def _clamp_score(value: object) -> int:
    try:
        return max(0, min(5, int(value)))
    except (TypeError, ValueError):
        return 0


def verdict_findings(
    verdict: dict, *, escalate_marginal_readability: bool = False
) -> tuple[list[str], list[str]]:
    """Map a review verdict to (hard issues, warnings) for the QA gate.

    Deliberately conservative: hard failures only for states no reasonable
    screenshot of a working game would produce. Mid scores stay warnings so a
    subjective VLM cannot start a regeneration loop — with one exception:
    readability 2/5 escalates to an issue while the caller still has minimal-
    patch repair budget (escalate_marginal_readability=True). 像素都市计划
    (2026-07-17) 的评审 2/5 逐条说中了用户投诉(文字过小/面板重叠/教程遮挡),
    却因 warning 档被整体丢弃;这类发现是可小 patch 修复的,不该白白流走。
    The "visual review:" prefix routes these to the quality minimal-patch path,
    so escalation never triggers a full regeneration.
    """
    issues: list[str] = []
    warnings: list[str] = []
    detail = "; ".join(verdict.get("top_issues") or []) or "no detail provided"
    aesthetic = int(verdict.get("aesthetic_score") or 0)
    readability = int(verdict.get("readability_score") or 0)
    if verdict.get("blank_or_broken"):
        issues.append(
            "visual review: screenshot shows blank or broken rendering — " + detail
        )
    elif verdict.get("looks_like_placeholder"):
        issues.append(
            "visual review: gameplay still looks like an unfinished placeholder stage — "
            + detail
        )
    elif aesthetic <= 1:
        issues.append(
            f"visual review: aesthetics far below bar ({aesthetic}/5) — " + detail
        )
    elif aesthetic == 2:
        warnings.append(
            f"visual review: visuals are flat ({aesthetic}/5) — " + detail
        )
    if readability <= 1 and not verdict.get("blank_or_broken"):
        issues.append(
            f"visual review: essential game state unreadable ({readability}/5) — "
            + detail
        )
    elif readability == 2:
        text = f"visual review: HUD readability is marginal ({readability}/5) — " + detail
        if escalate_marginal_readability:
            issues.append(text)
        else:
            warnings.append(text)
    return issues, warnings
