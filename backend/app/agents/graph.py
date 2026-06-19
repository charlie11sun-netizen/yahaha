"""固定 LangGraph 顶层工作流（docs/multi-agent_design.md §7.2）。

safety_intake → intent_spec → asset_processing → game_design → code_generation → build_validation
build_validation 失败：repair_code（≤2）→ 仍失败则 replan_game_design（≤1）→ 仍失败则 failed。
顶层固定，保证安全检查/构建校验/上传不被跳过；智能发生在节点内部。
"""
from langgraph.graph import END, START, StateGraph

from app.agents import nodes
from app.agents.state import GenerationState
from app.agents.tracing import logged


def build_graph():
    g = StateGraph(GenerationState)

    # 用 logged() 包住每个节点：开始写 running 步骤、结束翻 done（前端实时可见）
    g.add_node("safety_intake", logged("safety_intake")(nodes.safety_intake_node))
    g.add_node("intent_spec", logged("intent_spec")(nodes.intent_spec_node))
    g.add_node("archetype_router", logged("archetype_router")(nodes.archetype_router_node))
    g.add_node("asset_processing", logged("asset_processing")(nodes.asset_processing_node))
    g.add_node("game_design", logged("game_design")(nodes.game_design_node))
    g.add_node("balance_plan", logged("balance_plan")(nodes.balance_plan_node))
    g.add_node("code_generation", logged("code_generation")(nodes.code_generation_node))
    g.add_node("build_validation", logged("build_validation")(nodes.build_validation_node))
    g.add_node("repair_code", logged("repair_code")(nodes.repair_code_node))
    g.add_node("replan_game_design", logged("replan_game_design")(nodes.replan_game_design_node))
    g.add_node("gameplay_qa", logged("gameplay_qa")(nodes.gameplay_qa_node))
    g.add_node("gameplay_repair", logged("gameplay_repair")(nodes.gameplay_repair_node))
    g.add_node("publish_artifact", logged("publish_artifact")(nodes.publish_artifact_node))
    g.add_node("failed", nodes.failed_node)
    g.add_node("done", nodes.done_node)

    g.add_edge(START, "safety_intake")
    g.add_conditional_edges("safety_intake", nodes.should_continue_after_safety,
                            {"intent_spec": "intent_spec", "failed": "failed"})
    g.add_edge("intent_spec", "archetype_router")
    g.add_edge("archetype_router", "asset_processing")
    g.add_edge("asset_processing", "game_design")
    g.add_edge("game_design", "balance_plan")
    g.add_edge("balance_plan", "code_generation")
    g.add_edge("code_generation", "build_validation")
    g.add_conditional_edges("build_validation", nodes.should_continue_after_validation,
                            {"gameplay_qa": "gameplay_qa", "repair_code": "repair_code",
                             "replan_game_design": "replan_game_design", "failed": "failed"})
    g.add_edge("repair_code", "build_validation")
    g.add_edge("replan_game_design", "balance_plan")
    g.add_conditional_edges("gameplay_qa", nodes.should_continue_after_gameplay_qa,
                            {"publish_artifact": "publish_artifact", "gameplay_repair": "gameplay_repair",
                             "replan_game_design": "replan_game_design", "failed": "failed"})
    g.add_edge("gameplay_repair", "code_generation")
    g.add_edge("publish_artifact", "done")
    g.add_edge("done", END)
    g.add_edge("failed", END)

    return g.compile()
