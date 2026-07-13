"""质量底线与去趋同语义的回归测试。

覆盖:gameplay QA 的反馈特效硬底线与占位替换检测、规划层"只补缺不覆盖"、
archetype 降级为元数据、design 丰富键(palette/signature_twist/sfx_events)保留、
作者链路可读 game-quality-bar skill。
"""
import json

from app.agents import validation_nodes
from app.agents.codegen import code_generation_node
from app.agents.planning_brief import _coerce_mechanic_plan
from app.agents.planning_nodes import archetype_router_node, content_plan_node, gameplay_planning_node
from app.agents.planning_routing import _merge_balance_into_design
from app.agents.planning_spec import _coerce_design
from app.agents.repair_session import RepairSession, available_skills

_PAD = "// pad\n" * 80  # 让拼接源码超过 QA 的 400 字节下限


def _vite_state(play_content: str, code_source: str = "author") -> dict:
    project_files = [
        {"path": "package.json", "content": "{}"},
        {"path": "index.html", "content": "<html><main id='game-container'></main></html>"},
        {"path": "src/main.ts", "content": "import Phaser from 'phaser';\nnew Phaser.Game({});"},
        # 库文件里故意含特效 token:必须被剔除,否则底线检查永真
        {"path": "src/systems/Juice.ts", "content": "export class Juice { shake(){} } // tweens.add particles"},
        {"path": "src/scenes/PlayScene.ts", "content": play_content},
    ]
    return {
        "dimension": "2d",
        "artifact_format": "phaser-vite/v1",
        "code_source": code_source,
        "game_spec": {"archetype": "topdown_collect"},
        "game_design": {},
        "validation_result": {"valid": True},
        "generated_files": [],
        "project_files": project_files,
    }


def test_gameplay_qa_fails_when_no_feedback_effects_wired():
    play = _PAD + "createCursorKeys(); // restart hint, no effects at all"
    result = validation_nodes._gameplay_qa(_vite_state(play, code_source="template"))
    assert any("no gameplay feedback effects" in issue for issue in result["issues"])


def test_gameplay_qa_passes_with_juice_usage_and_flags_missing_audio():
    play = _PAD + "createCursorKeys();\nthis.juice.shake(0.01, 100); // restart"
    result = validation_nodes._gameplay_qa(_vite_state(play, code_source="template"))
    assert not any("no gameplay feedback effects" in issue for issue in result["issues"])
    assert any("no audio usage" in warning for warning in result["warnings"])
    assert result["passed"], result["issues"]


def test_gameplay_qa_rejects_unreplaced_placeholder_only_for_authored_projects():
    play = _PAD + "// GW_PLACEHOLDER_GAMEPLAY\ncreateCursorKeys();\nthis.juice.shake(0.01); // restart"
    authored = validation_nodes._gameplay_qa(_vite_state(play, code_source="author"))
    assert any("GW_PLACEHOLDER_GAMEPLAY" in issue for issue in authored["issues"])
    fallback = validation_nodes._gameplay_qa(_vite_state(play, code_source="template"))
    assert not any("GW_PLACEHOLDER_GAMEPLAY" in issue for issue in fallback["issues"])


def test_archetype_router_keeps_model_genre_and_core_loop():
    out = archetype_router_node(
        {
            "dimension": "2d",
            "prompt": "a rooftop platformer where you flip gravity",
            "game_spec": {
                "title": "Roof Flip",
                "genre": "platformer",
                "core_loop": "run, jump and flip gravity across rooftops",
            },
        }
    )
    spec = out["game_spec"]
    assert spec["genre"] == "platformer"
    assert spec["core_loop"] == "run, jump and flip gravity across rooftops"
    assert spec["archetype"]  # 元数据仍然打标


def test_gameplay_planning_combines_brief_and_mechanics_in_one_model_call(monkeypatch):
    calls = []

    def fake_chat(system_prompt, user_prompt):
        calls.append((system_prompt, user_prompt))
        return json.dumps(
            {
                "expanded_brief": {
                    "player_fantasy": "command a storm fighter",
                    "core_verbs": ["fly", "shoot", "dodge"],
                },
                "mechanic_plan": {
                    "archetype_hint": "vertical_shooter",
                    "primary_action": "shoot",
                    "signature_twist": "lightning chains through marked enemies",
                },
            }
        ), 37

    monkeypatch.setattr("app.agents.planning_nodes.llm.chat", fake_chat)
    out = gameplay_planning_node(
        {
            "use_real": True,
            "prompt": "a storm fighter vertical shooter",
            "game_spec": {"title": "Storm Wing", "genre": "shooter"},
        }
    )

    assert len(calls) == 1
    assert out["_agent"] == "GameplayPlanningAgent"
    assert out["_tokens_delta"] == 37
    assert out["expanded_brief"]["player_fantasy"] == "command a storm fighter"
    assert out["mechanic_plan"]["signature_twist"] == "lightning chains through marked enemies"


def test_generation_graph_has_one_combined_gameplay_planning_node():
    from app.agents.graph import build_graph

    graph = build_graph().get_graph()
    edges = {(edge.source, edge.target) for edge in graph.edges}

    assert "gameplay_planning" in graph.nodes
    assert "brief_expansion" not in graph.nodes
    assert "mechanic_planner" not in graph.nodes
    assert ("intent_spec", "gameplay_planning") in edges
    assert ("gameplay_planning", "archetype_router") in edges


def test_content_plan_only_fills_gap_when_design_lacks_waves():
    base = {
        "prompt": "collect gems",
        "game_spec": {"title": "Gems", "genre": "arcade", "archetype": "topdown_collect"},
    }
    with_waves = content_plan_node({**base, "game_design": {"waves": [{"t": 0, "spawn": "few"}]}})
    assert "content_plan" not in with_waves["game_design"]
    without_waves = content_plan_node({**base, "game_design": {}})
    assert without_waves["game_design"].get("content_plan")


def test_balance_merge_does_not_override_model_pacing():
    merged = _merge_balance_into_design(
        {"rules": {"survive_seconds": 95}},
        "topdown_collect",
        {"round_seconds": 65, "target_score": 170},
    )
    assert merged["rules"]["survive_seconds"] == 95
    assert merged["balance"]["target_score"] == 170


def test_coerce_design_preserves_identity_keys():
    design = _coerce_design(
        {
            "palette": {"bg": "#101820", "primary": "#f2aa4c"},
            "signature_twist": "the floor is lava every 10 seconds",
            "sfx_events": ["pickup", "lava_rise"],
        },
        {"genre": "arcade"},
    )
    assert design["palette"]["primary"] == "#f2aa4c"
    assert design["signature_twist"].startswith("the floor is lava")
    assert design["sfx_events"] == ["pickup", "lava_rise"]


def test_coerce_mechanic_plan_keeps_signature_twist():
    plan = _coerce_mechanic_plan({"signature_twist": "gravity flips on every pickup"}, {}, {}, "prompt")
    assert plan["signature_twist"] == "gravity flips on every pickup"


def test_codegen_reports_template_code_source_offline():
    out = code_generation_node(
        {
            "dimension": "2d",
            "use_real": False,
            "game_spec": {"title": "Sourced", "archetype": "topdown_collect"},
            "game_design": {},
        }
    )
    assert out["code_source"] == "template"


def test_quality_bar_skill_available_to_agents():
    assert "game-quality-bar" in available_skills()
    body = RepairSession.from_files(
        [{"path": "index.html", "content": "<html></html>"}]
    ).read_skill("game-quality-bar")
    assert "hitStop" in body and "risk-reward" in body and "GW_PLACEHOLDER_GAMEPLAY" in body
