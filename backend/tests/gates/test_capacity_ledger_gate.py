"""跨类型可行性账本门禁回归。

取证:win_feasibility 散文只对"首领窗口"算账(9000 血 vs 200 DPS×55s),
"整波约需 260 DPS"系拍脑袋;作者层自行发明的第 20 波构成(boss+8精英+16石壳
+8治疗+24斥候≈25400 原始 HP,含群疗)把真实需求抬到 ~40000 原始伤害,理论满配
完美命中率≈43000——零余量,现实覆盖率下数学不可赢。修复:设计层必须产出
机器可读的 rules.win_feasibility_ledger{threat_effective_hp, deliverable_damage},
契约门禁做纯算术校验(deliverable ≥ 1.3×threat);账本缺失不拦(兼容旧契约,
提示词层施压),存在则严格——对模型自己声明的数字做比值判定,零误报。

账本现在同时支持通用 required/available checks。距离、跳跃、节奏、解谜容量、
经济与战斗都走同一校验器；非战斗游戏不能再被塔防字段误伤。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.agents import author_prompts, prompts
from app.agents.design_contract import (
    ContractCompileError,
    compile_design_contract,
    freeze_contract,
    validate_contract,
)

_SKILL_PATH = Path(__file__).resolve().parents[2] / "app" / "agents" / "skills" / "game-quality-bar" / "SKILL.md"


def _draft(ledger: dict | None):
    rules = {
        "win": "clear all 20 waves",
        "lose": "gate reaches 0",
        "win_feasibility": "prose arithmetic ...",
    }
    if ledger is not None:
        rules["win_feasibility_ledger"] = ledger
    spec = {"title": "Ledger TD", "genre": "tower_defense", "archetype": "tower_defense"}
    design = {
        "archetype": "tower_defense",
        "player": {"visual": "commander"},
        "entities": [{"name": "Grunt", "role": "enemy", "visual": "grey grunt"}],
        "rules": rules,
        "ui": {"show_score": True},
    }
    return compile_design_contract(spec, design)


def _generic_draft(
    checks: list[dict],
    *,
    genre: str = "runner",
    rules: dict | None = None,
):
    merged_rules = {
        "win": "reach the authored objective",
        "lose": "exhaust the genre-specific failure budget",
        "win_feasibility": "mechanic-specific arithmetic",
        "win_feasibility_ledger": {
            "schema_version": "gameweave.feasibility/1",
            "checks": checks,
        },
        **(rules or {}),
    }
    return compile_design_contract(
        {"title": f"Generic {genre}", "genre": genre, "archetype": genre},
        {
            "archetype": genre,
            "player": {"visual": "player"},
            "rules": merged_rules,
            "ui": {"show_score": True},
        },
    )


def test_gate_passes_with_sufficient_headroom():
    contract = freeze_contract(_draft({"heaviest_wave": "20", "threat_effective_hp": 20000, "deliverable_damage": 27000}))
    gate = validate_contract(contract, require_frozen=True)
    assert gate.passed, gate.issues
    assert gate.metrics.get("capacity_headroom") == pytest.approx(0.35)


def test_gate_blocks_insufficient_headroom():
    gate = validate_contract(_draft({"heaviest_wave": "20", "threat_effective_hp": 25400, "deliverable_damage": 26000}))
    assert not gate.passed
    assert any("insufficient capacity headroom" in issue for issue in gate.issues)


def test_gate_blocks_malformed_ledger():
    gate = validate_contract(_draft({"threat_effective_hp": "很多", "deliverable_damage": 26000}))
    assert not gate.passed
    assert any("numeric threat_effective_hp" in issue for issue in gate.issues)

    gate = validate_contract(_draft({"threat_effective_hp": 0, "deliverable_damage": 26000}))
    assert not gate.passed
    assert any("must be positive" in issue for issue in gate.issues)


def test_freeze_refuses_underpowered_ledger():
    # 坏账本连冻结都不允许:契约修复回路在冻结前就把矛盾打回设计侧。
    with pytest.raises(ContractCompileError, match="insufficient capacity headroom"):
        freeze_contract(_draft({"heaviest_wave": "20", "threat_effective_hp": 25400, "deliverable_damage": 26000}))


def test_gate_is_silent_without_ledger():
    contract = freeze_contract(_draft(None))
    gate = validate_contract(contract, require_frozen=True)
    assert gate.passed, gate.issues
    assert "capacity_headroom" not in gate.metrics


def test_non_combat_legacy_na_placeholder_is_not_treated_as_bad_arithmetic():
    contract = compile_design_contract(
        {"title": "Pixel Runner", "genre": "runner", "archetype": "lane_runner"},
        {
            "archetype": "lane_runner",
            "player": {"visual": "runner"},
            "rules": {
                "win": "reach 3000m",
                "lose": "lives reach zero",
                "win_feasibility_ledger": {
                    "heaviest_wave": "不适用：本作是无战斗自动跑酷",
                    "threat_effective_hp": 0,
                    "deliverable_damage": 0,
                    "first_wave_total_hp": 0,
                    "opening_deliverable_damage": 0,
                },
            },
        },
    )
    gate = validate_contract(contract)
    assert gate.passed, gate.issues
    assert gate.metrics["skipped_feasibility_ledger_count"] == 1


def test_generic_runner_checks_pass_without_combat_fields():
    contract = freeze_contract(
        _generic_draft(
            [
                {
                    "id": "track_capacity",
                    "required": 3000,
                    "available": 4320,
                    "minimum_ratio": 1.3,
                    "unit": "meters",
                    "evidence": "24 templates x 180m",
                },
                {
                    "id": "jump_reach",
                    "required": 140,
                    "available": 301,
                    "minimum_ratio": 1.2,
                    "unit": "pixels",
                    "evidence": "speed x conservative airtime",
                },
            ]
        )
    )
    gate = validate_contract(contract, require_frozen=True)
    assert gate.passed, gate.issues
    assert gate.metrics["feasibility_check_count"] == 2
    assert gate.metrics["feasibility_headroom"]["track_capacity"] == pytest.approx(
        0.44
    )
    assert gate.metrics["feasibility_headroom"]["jump_reach"] == pytest.approx(
        301 / 140 - 1,
        abs=1e-4,
    )


def test_generic_checks_block_any_genre_with_insufficient_headroom():
    gate = validate_contract(
        _generic_draft(
            [
                {
                    "id": "economy_bootstrap",
                    "required": 100,
                    "available": 110,
                    "minimum_ratio": 1.2,
                    "unit": "credits",
                    "evidence": "starting funds vs tutorial purchases",
                }
            ],
            genre="management",
        )
    )
    assert not gate.passed
    assert any(
        "check economy_bootstrap has insufficient headroom" in issue
        for issue in gate.issues
    )


@pytest.mark.parametrize(
    "check",
    [
        {
            "id": "bad_zero",
            "required": 0,
            "available": 10,
            "minimum_ratio": 1.0,
        },
        {
            "id": "bad_ratio",
            "required": 10,
            "available": 20,
            "minimum_ratio": 0.9,
        },
    ],
)
def test_generic_checks_reject_zero_placeholders_and_invalid_ratios(check):
    gate = validate_contract(_generic_draft([check], genre="puzzle"))
    assert not gate.passed


def test_gate_verifies_opening_vs_first_wave_pair():
    # 弦长取证(2026-07-21 二次):教程开局 2 塔按射程弦长只杀 3/10,第一波漏 7。
    # 账本必须让"开局输出"直面"第一波总血",门禁按 1.2 倍余量拦截。
    good = {
        "heaviest_wave": "20",
        "threat_effective_hp": 20000,
        "deliverable_damage": 27000,
        "first_wave_total_hp": 700,
        "opening_deliverable_damage": 900,
    }
    contract = freeze_contract(_draft(good))
    gate = validate_contract(contract, require_frozen=True)
    assert gate.passed, gate.issues
    assert gate.metrics.get("opening_headroom") == pytest.approx(900 / 700 - 1.0, abs=1e-4)

    weak_opening = dict(good, opening_deliverable_damage=750)
    gate = validate_contract(_draft(weak_opening))
    assert not gate.passed
    assert any("insufficient opening headroom" in issue for issue in gate.issues)

    half_pair = dict(good)
    del half_pair["opening_deliverable_damage"]
    gate = validate_contract(_draft(half_pair))
    assert not gate.passed
    assert any("numeric first_wave_total_hp and opening_deliverable_damage" in issue for issue in gate.issues)


def test_design_prompt_teaches_chord_arithmetic_and_opening_check():
    prompt = prompts.GAME_DESIGN_SYSTEM_PROMPT
    assert "chord = 2 x sqrt(range^2 - perpendicular_distance^2)" in prompt
    assert "NOT the enemy's 26-second full walk" in prompt
    assert "opening combat, only when the game has authored combat waves/phases" in prompt
    assert "combat_capacity" in prompt and "opening_combat" in prompt
    assert "ZERO leaks" in prompt


def test_author_and_skill_carry_chord_discipline():
    assert "chord of its\n" not in author_prompts._DESIGN_CONTRACT_INSTRUCTIONS  # 单行文案,防换行破坏断言
    assert "opening_deliverable_damage basis" in author_prompts._DESIGN_CONTRACT_INSTRUCTIONS
    text = _SKILL_PATH.read_text(encoding="utf-8")
    assert "2*sqrt(range" in text
    assert "recheck the\nopening-vs-wave-1" in text.replace("\r\n", "\n")


def test_design_prompt_demands_wave_ledger_arithmetic():
    prompt = prompts.GAME_DESIGN_SYSTEM_PROMPT
    assert "win_feasibility_ledger" in prompt
    assert "threat_effective_hp" in prompt and "deliverable_damage" in prompt
    # 需求侧必须含治疗/护盾等效,供给侧必须按 ≤60% 命中率折算
    assert "heal rate x targets in range x expected lifetime" in prompt
    assert "<=60%" in prompt
    assert "never budget 100%" in prompt


def test_design_prompt_uses_genre_neutral_feasibility_checks():
    prompt = prompts.GAME_DESIGN_SYSTEM_PROMPT
    assert '"schema_version":"gameweave.feasibility/1"' in prompt
    assert '"required":<positive number' in prompt
    assert '"available":<positive number' in prompt
    assert "never use 0 or \"N/A\" placeholders" in prompt
    assert "never emit combat fields for a non-combat game" in prompt


def test_author_layers_enforce_single_balance_source_and_frozen_composition():
    contract_instructions = author_prompts._DESIGN_CONTRACT_INSTRUCTIONS
    assert "Balance constants live in ONE place" in contract_instructions
    assert "matches the design's declared composition exactly" in contract_instructions
    assert "SINGLE owner of balance data" in author_prompts._WORLD_INSTRUCTIONS
    assert "instead of hand-writing your own copy" in author_prompts._RULES_INSTRUCTIONS
    assert "delete the duplicate" in author_prompts._INTEGRATION_INSTRUCTIONS


def test_quality_bar_skill_documents_balance_home_and_wave_budget():
    text = _SKILL_PATH.read_text(encoding="utf-8")
    assert "Balance numbers have ONE home" in text
    assert "capacity ledger" in text
    assert "never pile on\nunits ad hoc" in text.replace("\r\n", "\n")


def test_ledger_survives_contract_hash_round_trip():
    ledger = {"heaviest_wave": "20", "threat_effective_hp": 20000, "deliverable_damage": 27000}
    contract = freeze_contract(_draft(ledger))
    payload = json.loads(contract.model_dump_json())
    found = [
        system["details"].get("win_feasibility_ledger")
        for system in payload["systems"]
        if system["details"].get("win_feasibility_ledger")
    ]
    assert found and found[0]["threat_effective_hp"] == 20000
