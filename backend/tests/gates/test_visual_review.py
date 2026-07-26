"""Offline coverage for the screenshot-based visual QA layer."""

from __future__ import annotations

import base64
import io
import random

from PIL import Image

from app.agents import visual_review
from app.agents.repair import _classify_gameplay_failure


def _png_b64(image: Image.Image) -> str:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def test_blank_screen_reason_flags_flat_frame():
    flat = Image.new("RGB", (320, 180), (12, 12, 20))
    reason = visual_review.blank_screen_reason(_png_b64(flat))
    assert reason is not None and "uniform" in reason


def test_blank_screen_reason_accepts_composed_scene():
    rng = random.Random(7)
    busy = Image.new("RGB", (320, 180))
    busy.putdata(
        [
            (rng.randrange(256), rng.randrange(256), rng.randrange(256))
            for _ in range(320 * 180)
        ]
    )
    assert visual_review.blank_screen_reason(_png_b64(busy)) is None


def test_blank_screen_reason_fails_open_on_garbage():
    assert visual_review.blank_screen_reason("not-a-png") is None


def test_review_screenshot_parses_model_verdict(monkeypatch):
    class _Result:
        text = (
            '{"aesthetic_score": 4, "readability_score": 9, "essential_text_readable": false,'
            ' "production_ui_clean": false,'
            ' "mechanic_clarity_score": 3, "actionable_elements_distinct": true,'
            ' "spatial_actions_visually_plausible": false,'
            ' "text_legibility_issues": ["pause label is clipped"], "looks_like_placeholder": false,'
            ' "debug_like_text_issues": ["pause body says physics is frozen"],'
            ' "mechanic_issues": ["jump target is wider than the visible arc"],'
            ' "blank_or_broken": false, "top_issues": ["HUD overlaps score"], "strengths": ["palette"]}'
        )

    captured = {}

    def fake_chat(system, user, **kwargs):
        captured.update(kwargs)
        captured["user"] = user
        assert "interaction director" in system
        return _Result()

    monkeypatch.setattr(visual_review.llm, "chat", fake_chat)
    monkeypatch.setattr(visual_review.settings, "VISUAL_REVIEW_ENABLED", True)
    verdict = visual_review.review_screenshot("Zm9v", {"title": "T"}, {})
    assert verdict == {
        "aesthetic_score": 4,
        "readability_score": 5,  # clamped to 0..5
        "mechanic_clarity_score": 3,
        "essential_text_readable": False,
        "production_ui_clean": False,
        "actionable_elements_distinct": True,
        "spatial_actions_visually_plausible": False,
        "text_legibility_issues": ["pause label is clipped"],
        "debug_like_text_issues": ["pause body says physics is frozen"],
        "mechanic_issues": ["jump target is wider than the visible arc"],
        "looks_like_placeholder": False,
        "blank_or_broken": False,
        "top_issues": ["HUD overlaps score"],
        "strengths": ["palette"],
    }
    assert captured["images_b64"] == ["Zm9v"]
    assert "core_loop" not in captured["user"]  # absent context is not invented


def test_review_screenshot_fails_open(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("gateway down")

    monkeypatch.setattr(visual_review.llm, "chat", boom)
    monkeypatch.setattr(visual_review.settings, "VISUAL_REVIEW_ENABLED", True)
    assert visual_review.review_screenshot("Zm9v", {}, {}) is None


def test_verdict_findings_policy_tiers():
    issues, warnings = visual_review.verdict_findings(
        {
            "aesthetic_score": 0,
            "readability_score": 3,
            "looks_like_placeholder": False,
            "blank_or_broken": True,
            "top_issues": ["black frame"],
            "strengths": [],
        }
    )
    assert any("blank or broken" in item for item in issues)

    issues, warnings = visual_review.verdict_findings(
        {
            "aesthetic_score": 2,
            "readability_score": 2,
            "looks_like_placeholder": False,
            "blank_or_broken": False,
            "top_issues": ["flat colors"],
            "strengths": [],
        }
    )
    assert issues == []
    assert len(warnings) == 2

    issues, _ = visual_review.verdict_findings(
        {
            "aesthetic_score": 4,
            "readability_score": 1,
            "looks_like_placeholder": False,
            "blank_or_broken": False,
            "top_issues": ["score invisible"],
            "strengths": ["nice palette"],
        }
    )
    assert any("unreadable" in item for item in issues)


def test_marginal_readability_escalates_only_with_repair_budget():
    """readability 2/5 在还有最小 patch 预算时升级为 issue(quality 修复路径);
    默认仍是 warning——主观 VLM 分数永远不该把任务推进 replan/failed。
    (像素都市计划 2026-07-17:2/5 评审逐条说中可读性问题却被 warning 档丢弃。)"""
    verdict = {
        "aesthetic_score": 3,
        "readability_score": 2,
        "looks_like_placeholder": False,
        "blank_or_broken": False,
        "top_issues": ["HUD text overlaps the score", "教程面板遮挡城市布局"],
        "strengths": [],
    }
    issues, warnings = visual_review.verdict_findings(
        verdict, escalate_marginal_readability=True
    )
    assert any(
        item.startswith("visual review:") and "readability" in item for item in issues
    )
    assert not any("readability" in item for item in warnings)
    # VLM 的具体发现进 issue 文本 → 修复简报可执行
    assert any("教程面板遮挡城市布局" in item for item in issues)
    label, patchable = _classify_gameplay_failure({"issues": issues})
    assert label == "quality" and patchable

    issues, warnings = visual_review.verdict_findings(verdict)
    assert issues == []
    assert any("readability" in item for item in warnings)


def test_unreadable_essential_text_never_downgrades_when_budget_is_exhausted():
    """The gate is genre-agnostic: a rhythm-game timing HUD is just as
    essential as shop text, and cannot become a warning after repair budget."""
    verdict = {
        "aesthetic_score": 4,
        "readability_score": 2,
        "essential_text_readable": False,
        "text_legibility_issues": [
            "rhythm timing prompt glyphs are closed by a heavy outline",
            "combo target is clipped by its panel",
        ],
        "looks_like_placeholder": False,
        "blank_or_broken": False,
        "top_issues": ["timing HUD is unreadable"],
        "strengths": ["coherent stage lighting"],
    }

    issues, warnings = visual_review.verdict_findings(verdict)

    assert any("essential text" in item for item in issues)
    assert any("heavy outline" in item for item in issues)
    assert not any("readability" in item for item in warnings)
    label, patchable = _classify_gameplay_failure({"issues": issues})
    assert label == "quality" and patchable == issues


def test_debug_like_player_copy_is_a_patchable_visual_issue():
    verdict = {
        "aesthetic_score": 4,
        "readability_score": 4,
        "mechanic_clarity_score": 4,
        "essential_text_readable": True,
        "production_ui_clean": False,
        "actionable_elements_distinct": True,
        "spatial_actions_visually_plausible": True,
        "text_legibility_issues": [],
        "debug_like_text_issues": [
            "slide prompt exposes beam clearance in pixels",
            "pause body tells the player that the rules layer freezes physics",
        ],
        "mechanic_issues": [],
        "looks_like_placeholder": False,
        "blank_or_broken": False,
        "top_issues": [],
        "strengths": ["coherent palette"],
    }

    issues, warnings = visual_review.verdict_findings(verdict)

    assert warnings == []
    assert any("debug or implementation evidence" in item for item in issues)
    assert any("beam clearance" in item for item in issues)
    label, patchable = _classify_gameplay_failure({"issues": issues})
    assert label == "quality" and patchable == issues


def test_mechanic_affordance_failure_is_a_patchable_issue():
    verdict = {
        "aesthetic_score": 4,
        "readability_score": 4,
        "mechanic_clarity_score": 1,
        "essential_text_readable": True,
        "actionable_elements_distinct": False,
        "spatial_actions_visually_plausible": False,
        "text_legibility_issues": [],
        "mechanic_issues": [
            "jump and slide hazards occupy the same ground band",
            "the jump hazard is wider than the visible clearance arc",
        ],
        "looks_like_placeholder": False,
        "blank_or_broken": False,
        "top_issues": [],
        "strengths": ["coherent palette"],
    }

    issues, warnings = visual_review.verdict_findings(verdict)

    assert not warnings
    assert any("mechanic affordances" in item for item in issues)
    assert any("same ground band" in item for item in issues)
    label, patchable = _classify_gameplay_failure({"issues": issues})
    assert label == "quality" and patchable == issues


def test_visual_issues_classify_as_quality_patchable():
    label, patchable = _classify_gameplay_failure(
        {
            "issues": [
                "visual review: aesthetics far below bar (1/5) — untextured rectangles",
            ]
        }
    )
    assert label == "quality"
    assert patchable

    label, patchable = _classify_gameplay_failure(
        {
            "issues": [
                "browser screenshot shows an essentially blank play screen while the loop is running — frame is essentially uniform (2 distinct colors, stddev 0.0)",
            ]
        }
    )
    assert label == "quality"
    assert patchable
