"""固定 LangGraph 顶层工作流（docs/multi-agent_design.md §7.2）。

safety_intake → intent_spec → gameplay_planning → archetype_router → game_design → content_plan → balance_plan → design_contract → contract_gate → asset_processing → asset_generation → code_generation → build_validation
build_validation 失败：repair_code（≤2）→ 仍失败则 replan_game_design（≤1）→ 仍失败则 failed。
gameplay_qa 失败：gameplay_repair（≤2）——浏览器运行时报错先走内层 agent 最小 patch，
patch 成功带产物回 build_validation 复检；玩法指标问题调 balance 后回 code_generation 重生成。
顶层固定，保证安全检查/构建校验/上传不被跳过；智能发生在节点内部。
"""
from langgraph.graph import END, START, StateGraph

from app.agents import nodes
from app.agents.state import GenerationState
from app.agents.tracing import logged


def build_graph(*, checkpointer=None):
    g = StateGraph(GenerationState)

    # 用 logged() 包住每个节点：开始写 running 步骤、结束翻 done（前端实时可见）
    g.add_node("safety_intake", logged("safety_intake")(nodes.safety_intake_node))
    g.add_node("memory_retrieval", logged("memory_retrieval")(nodes.memory_retrieval_node))
    g.add_node("intent_spec", logged("intent_spec")(nodes.intent_spec_node))
    g.add_node("gameplay_planning", logged("gameplay_planning")(nodes.gameplay_planning_node))
    g.add_node("archetype_router", logged("archetype_router")(nodes.archetype_router_node))
    g.add_node("asset_processing", logged("asset_processing")(nodes.asset_processing_node))
    g.add_node("asset_generation", logged("asset_generation")(nodes.asset_generation_node))
    g.add_node("game_design", logged("game_design")(nodes.game_design_node))
    g.add_node("content_plan", logged("content_plan")(nodes.content_plan_node))
    g.add_node("balance_plan", logged("balance_plan")(nodes.balance_plan_node))
    g.add_node("design_contract", logged("design_contract")(nodes.design_contract_node))
    g.add_node("contract_gate", logged("contract_gate")(nodes.contract_gate_node))
    g.add_node("code_generation", logged("code_generation")(nodes.code_generation_node))
    g.add_node("project_build", logged("project_build")(nodes.project_build_node))
    g.add_node("build_validation", logged("build_validation")(nodes.build_validation_node))
    g.add_node("repair_code", logged("repair_code")(nodes.repair_code_node))
    g.add_node("replan_game_design", logged("replan_game_design")(nodes.replan_game_design_node))
    g.add_node("gameplay_qa", logged("gameplay_qa")(nodes.gameplay_qa_node))
    g.add_node("gameplay_repair", logged("gameplay_repair")(nodes.gameplay_repair_node))
    g.add_node("publish_artifact", logged("publish_artifact")(nodes.publish_artifact_node))
    g.add_node("feedback_understanding", logged("feedback_understanding")(nodes.feedback_understanding_node))
    g.add_node("code_revision", logged("code_revision")(nodes.code_revision_node))
    g.add_node("revision_repair", logged("revision_repair")(nodes.revision_repair_node))
    g.add_node("publish_revision", logged("publish_revision")(nodes.publish_revision_node))
    g.add_node("publish_remix", logged("publish_remix")(nodes.publish_remix_node))
    g.add_node("memory_update", logged("memory_update")(nodes.memory_update_node))
    g.add_node("failed", nodes.failed_node)
    g.add_node("done", nodes.done_node)

    g.add_edge(START, "safety_intake")
    g.add_conditional_edges("safety_intake", nodes.should_continue_after_safety,
                            {"memory_retrieval": "memory_retrieval",
                             "failed": "failed"})
    g.add_conditional_edges("memory_retrieval", nodes.next_after_memory_retrieval,
                            {"intent_spec": "intent_spec", "feedback_understanding": "feedback_understanding"})
    g.add_edge("intent_spec", "gameplay_planning")
    g.add_edge("gameplay_planning", "archetype_router")
    g.add_edge("archetype_router", "game_design")
    g.add_edge("game_design", "content_plan")
    g.add_edge("content_plan", "balance_plan")
    g.add_edge("balance_plan", "design_contract")
    g.add_edge("design_contract", "contract_gate")
    g.add_conditional_edges("contract_gate", nodes.should_continue_after_contract_gate,
                            {"asset_processing": "asset_processing", "code_revision": "code_revision", "failed": "failed"})
    g.add_edge("asset_processing", "asset_generation")
    g.add_conditional_edges(
        "asset_generation",
        nodes.should_continue_after_asset_generation,
        {"code_generation": "code_generation", "code_revision": "code_revision"},
    )
    g.add_edge("code_generation", "project_build")
    g.add_edge("project_build", "build_validation")
    g.add_conditional_edges("build_validation", nodes.should_continue_after_validation,
                            {"gameplay_qa": "gameplay_qa", "repair_code": "repair_code",
                             "replan_game_design": "replan_game_design", "revision_repair": "revision_repair",
                             "failed": "failed"})
    g.add_edge("repair_code", "project_build")
    g.add_edge("replan_game_design", "balance_plan")
    g.add_conditional_edges("gameplay_qa", nodes.should_continue_after_gameplay_qa,
                            {"publish_artifact": "publish_artifact", "gameplay_repair": "gameplay_repair",
                             "replan_game_design": "replan_game_design", "publish_revision": "publish_revision",
                             "publish_remix": "publish_remix", "revision_repair": "revision_repair",
                             "failed": "failed"})
    g.add_conditional_edges("gameplay_repair", nodes.next_after_gameplay_repair,
                            {"project_build": "project_build", "balance_plan": "balance_plan", "code_generation": "code_generation"})
    g.add_edge("publish_artifact", "memory_update")
    g.add_edge("feedback_understanding", "design_contract")
    g.add_edge("code_revision", "project_build")
    g.add_edge("revision_repair", "project_build")
    g.add_edge("publish_revision", "memory_update")
    g.add_edge("publish_remix", "memory_update")
    g.add_edge("memory_update", "done")
    g.add_edge("done", END)
    g.add_edge("failed", END)

    return g.compile(checkpointer=checkpointer)
