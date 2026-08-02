"""经济动作"提交前预览"纪律的层间一致性回归(三线守望 2026-07-20 取证后新增).

取证:契约有射程预览要求、有建造价,但"升级要花多少、提升什么"在设计/契约/
作者/QA 四层全部缺位——玩家面对裸的"U 升级"按钮只能盲点。修复把同一纪律
铺进五层;本文件断言各层文案存在,防止后续轮次改提示词时被误删。
VLM 截图评审的发现走既有 "visual review:" 前缀 → quality 最小 patch 路由,
无需新增确定性静态检查(第四轮教训:误报会点燃百万 token 重生成循环)。
"""
from __future__ import annotations

from pathlib import Path

from app.agents import author_prompts, prompts, visual_review
from app.agents.repair import _QUALITY_QA_PATCHABLE

_SKILL_PATH = Path(__file__).resolve().parents[2] / "app" / "agents" / "skills" / "game-quality-bar" / "SKILL.md"


def test_planning_constitution_requires_commitment_preview():
    constitution = prompts.PLANNING_SHARED_CACHE_PREFIX
    assert "spends or refunds a resource" in constitution
    assert "unaffordable shows the shortfall" in constitution
    assert "MAX" in constitution


def test_design_prompt_declares_economy_affordance_rule():
    prompt = prompts.GAME_DESIGN_SYSTEM_PROMPT
    assert "Economy affordance rule" in prompt
    assert "cost AND each stat that changes per level" in prompt
    assert "current→next" in prompt
    # 既有的空间 affordance 规则不能被挤掉
    assert "Affordance rule" in prompt


def test_contract_instructions_add_commitment_preview_acceptance():
    instructions = author_prompts._DESIGN_CONTRACT_INSTRUCTIONS
    assert "commitment preview" in instructions
    assert "current→next values of the stats that change" in instructions
    assert "MAX state" in instructions


def test_presentation_rules_require_price_and_delta_from_rules_data():
    instructions = author_prompts._PRESENTATION_INSTRUCTIONS
    assert "spends or refunds currency" in instructions
    assert "current→next" in instructions
    # 数值必须来自规则/内容层数据,禁止 UI 硬编码副本
    assert "never hard-code copies in UI" in instructions
    assert '"MAX"' in instructions


def test_quality_bar_skill_documents_spend_preview():
    text = _SKILL_PATH.read_text(encoding="utf-8")
    assert "Spending is a deal the player can read before taking it" in text
    assert "towerData.levels[tower.level + 1]" in text
    assert "no visible\n  price or benefit preview" in text.replace("\r\n", "\n")


def test_visual_review_rubric_flags_priceless_commerce_controls():
    rubric = visual_review._REVIEW_SYSTEM
    assert "Commerce readability" in rubric
    assert "upgrade button shows no cost or stat preview" in rubric


def test_visual_review_findings_route_to_minimal_patch():
    # VLM 的新发现以 "visual review:" 前缀出现,必须继续命中 quality 最小
    # patch 分类,而不是掉进 balance 调参 + 整包重生成。
    assert any(prefix == "visual review:" for prefix in _QUALITY_QA_PATCHABLE)
