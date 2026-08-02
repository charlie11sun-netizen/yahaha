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

_REVIEW_SYSTEM = """You are a strict but fair game art and interaction director reviewing ONE gameplay screenshot of a small browser game (embedded at roughly 840x470). Judge only what is visible.

Return only a JSON object:
{"aesthetic_score": 0-5, "readability_score": 0-5, "mechanic_clarity_score": 0-5, "essential_text_readable": bool, "production_ui_clean": bool|null, "actionable_elements_distinct": bool|null, "spatial_actions_visually_plausible": bool|null, "text_legibility_issues": ["..."], "debug_like_text_issues": ["..."], "mechanic_issues": ["..."], "looks_like_placeholder": bool, "blank_or_broken": bool, "top_issues": ["..."], "strengths": ["..."]}

Scoring anchors:
- aesthetic_score: 0-1 broken/empty or raw untextured primitives only; 2 functional but visually flat (no palette identity, no lighting/contrast hierarchy); 3 coherent style with readable hierarchy; 4 polished (layered background, consistent palette, visible feedback effects); 5 shippable arcade quality.
- readability_score: 0-1 essential state unreadable or missing HUD; 2 cramped/low-contrast or overlapping text; 3+ the player can read state at a glance.
- mechanic_clarity_score: 0-1 visible objects contradict the required actions or the player cannot tell what is actionable; 2 actions/targets are weakly distinguished or their clearances look implausible; 3+ actionable roles and consequences are visually legible.
- essential_text_readable: false when ANY text needed to play or make a decision cannot be read accurately at the CAPTURED screenshot size. This includes HUD state, objectives, instructions, choice labels, prices/costs, upgrade effects, pause/restart controls, and failure/win state. Fail it for undersized or pixelated glyphs, overly thick outlines that close glyph interiors, low contrast, overlap, clipping, or text packed beyond its panel. Games that communicate without essential text may set it true; do not invent a text requirement.
- production_ui_clean: false when normal player-facing text looks like developer, QA, acceptance, or collision evidence rather than finished game copy. Examples: collision/hitbox/body sizes, pixel or coordinate measurements, milliseconds, clearance arithmetic, rule-layer/physics/state-machine notes, Probe/QA/debug/test labels, implementation freeze assertions, or instructions addressed to a developer. Numeric values genuinely used by the player (health, speed, distance, rhythm offset, prices, simulation statistics) are legitimate. Set null only when no text is visible.
- actionable_elements_distinct: false when player-controlled elements, threats, goals, blockers, targets, or choices that require different responses look functionally interchangeable. Set null when the screenshot/context does not expose multiple actionable roles.
- spatial_actions_visually_plausible: for visible spatial or timed interactions, false when the advertised action cannot plausibly clear/reach/hit/fit the target, or when targets requiring different actions occupy the same visual envelope and differ only by a label. Examples include jump and duck hazards on the same ground band, an overhead blocker with no passable gap, an attack whose visible reach cannot touch its target, or a placement preview that does not fit its footprint. Set null when one still frame cannot judge any relevant spatial interaction; do not invent motion.
- text_legibility_issues: at most 4 short observations naming the affected element and visible cause. Leave empty only when essential_text_readable is true.
- debug_like_text_issues: at most 4 short observations naming visible implementation/debug-like copy and why a player does not need it. Leave empty when production_ui_clean is true or null.
- mechanic_issues: at most 4 short observations naming the object/action pair and the visible geometry or affordance defect. Leave empty when both mechanic booleans are true or null.
- looks_like_placeholder: true when the scene is mostly bare colored rectangles/circles with no art direction, or an obviously unfinished stage.
- blank_or_broken: true for an essentially empty/black/white frame, a missing-texture checkerboard, or garbled rendering.
- top_issues: at most 4 short, concrete, fixable observations (e.g. "HUD text overlaps the score", "player sprite floats above the platform shadowless"), most severe first.
- strengths: at most 2, only if genuinely present.
- Commerce readability: if the screenshot shows controls that spend or refund currency (build/upgrade/sell/unlock buttons, shop entries), each must carry a visible price or an explicit MAX/refund state, and an upgrade affordance should preview what improves. A spend control with no visible cost, or an upgrade with no visible benefit, is a top_issue (e.g. "upgrade button shows no cost or stat preview") and caps readability_score at 3.

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
    design_body = design.get("design") if isinstance(design.get("design"), dict) else design
    entities = design_body.get("entities") if isinstance(design_body, dict) else []
    context = {
        "title": spec.get("title"),
        "genre": spec.get("genre"),
        "theme": spec.get("theme"),
        "visual_style": spec.get("visual_style"),
        "core_loop": spec.get("core_loop"),
        "controls": spec.get("controls"),
        "palette": design_body.get("palette") if isinstance(design_body, dict) else None,
        "player": design_body.get("player") if isinstance(design_body, dict) else None,
        "interaction_profiles": (
            list(design_body.get("interaction_profiles") or [])[:12]
            if isinstance(design_body, dict)
            and isinstance(design_body.get("interaction_profiles"), list)
            else []
        ),
        "entities": [
            {
                key: entity.get(key)
                for key in ("name", "role", "movement", "behavior")
                if entity.get(key)
            }
            for entity in (entities or [])[:8]
            if isinstance(entity, dict)
        ],
    }
    prompt = (
        "Game context (for intent only, judge the pixels):\n"
        + json.dumps({k: v for k, v in context.items() if v}, ensure_ascii=False)[:1800]
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
        "mechanic_clarity_score": _optional_score(
            verdict.get("mechanic_clarity_score")
        ),
        "essential_text_readable": (
            verdict.get("essential_text_readable")
            if isinstance(verdict.get("essential_text_readable"), bool)
            else None
        ),
        "production_ui_clean": _optional_bool(verdict.get("production_ui_clean")),
        "actionable_elements_distinct": _optional_bool(
            verdict.get("actionable_elements_distinct")
        ),
        "spatial_actions_visually_plausible": _optional_bool(
            verdict.get("spatial_actions_visually_plausible")
        ),
        "text_legibility_issues": [
            str(item)[:200]
            for item in (verdict.get("text_legibility_issues") or [])[:4]
        ],
        "debug_like_text_issues": [
            str(item)[:200]
            for item in (verdict.get("debug_like_text_issues") or [])[:4]
        ],
        "mechanic_issues": [
            str(item)[:200] for item in (verdict.get("mechanic_issues") or [])[:4]
        ],
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


def _optional_score(value: object) -> int | None:
    if value is None:
        return None
    return _clamp_score(value)


def _optional_bool(value: object) -> bool | None:
    return value if isinstance(value, bool) else None


def verdict_findings(
    verdict: dict, *, escalate_marginal_readability: bool = False
) -> tuple[list[str], list[str]]:
    """Map a review verdict to (hard issues, warnings) for the QA gate.

    Mid scores normally stay warnings so a subjective VLM cannot start a
    regeneration loop. A structured failure of essential text is different:
    unreadable controls/state make the game unusable, so it remains a hard
    issue at every budget level and for generation, revision, and remix alike.
    A generic readability 2/5 also escalates while minimal-patch budget remains.
    The "visual review:" prefix routes both cases to the quality patch path.
    """
    issues: list[str] = []
    warnings: list[str] = []
    detail = "; ".join(verdict.get("top_issues") or []) or "no detail provided"
    text_detail = (
        "; ".join(verdict.get("text_legibility_issues") or []) or detail
    )
    debug_text_detail = (
        "; ".join(verdict.get("debug_like_text_issues") or []) or detail
    )
    mechanic_detail = "; ".join(verdict.get("mechanic_issues") or []) or detail
    aesthetic = int(verdict.get("aesthetic_score") or 0)
    readability = int(verdict.get("readability_score") or 0)
    essential_text_failed = verdict.get("essential_text_readable") is False
    production_ui_failed = verdict.get("production_ui_clean") is False
    mechanic_score = verdict.get("mechanic_clarity_score")
    mechanic_failed = (
        verdict.get("actionable_elements_distinct") is False
        or verdict.get("spatial_actions_visually_plausible") is False
    )
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
    if essential_text_failed and not verdict.get("blank_or_broken"):
        issues.append(
            "visual review: essential text is not reliably legible at the captured play size — "
            + text_detail
        )
    elif readability <= 1 and not verdict.get("blank_or_broken"):
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
    if production_ui_failed and not verdict.get("blank_or_broken"):
        issues.append(
            "visual review: player-visible copy exposes debug or implementation evidence - "
            + debug_text_detail
        )
    if mechanic_failed and not verdict.get("blank_or_broken"):
        issues.append(
            "visual review: mechanic affordances are not visually distinct or spatially plausible - "
            + mechanic_detail
        )
    elif (
        mechanic_score is not None
        and int(mechanic_score) <= 1
        and not verdict.get("blank_or_broken")
    ):
        issues.append(
            f"visual review: mechanic clarity is below the playable bar ({int(mechanic_score)}/5) - "
            + mechanic_detail
        )
    elif mechanic_score is not None and int(mechanic_score) == 2:
        warnings.append(
            f"visual review: mechanic affordances are marginal ({int(mechanic_score)}/5) - "
            + mechanic_detail
        )
    return issues, warnings
