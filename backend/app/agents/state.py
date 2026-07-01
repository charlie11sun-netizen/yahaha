"""LangGraph 共享状态与步骤常量（对应 docs/multi-agent_design.md §5）。"""
from typing import Any, Optional, TypedDict

MAX_REPAIR = 2
MAX_REPLAN = 1
MAX_GAMEPLAY_REPAIR = 2

# step -> (agent_name, 展示名)
STEP_META: dict[str, tuple[str, str]] = {
    "safety_intake": ("SafetyIntakeAgent", "Safety Intake"),
    "memory_retrieval": ("MemoryRetrievalAgent", "Retrieve Memory"),
    "intent_spec": ("IntentSpecAgent", "Intent Spec"),
    "brief_expansion": ("BriefExpansionAgent", "Brief Expansion"),
    "mechanic_planner": ("MechanicPlannerAgent", "Mechanic Planner"),
    "archetype_router": ("ArchetypeRouterAgent", "Archetype Router"),
    "asset_processing": ("AssetAgent", "Asset Processing"),
    "game_design": ("GameDesignAgent", "Game Design"),
    "content_plan": ("ContentPlanAgent", "Content Plan"),
    "balance_plan": ("BalanceAgent", "Balance Plan"),
    "code_generation": ("GameCodeAgent", "Code Generation"),
    "build_validation": ("BuildValidateAgent", "Build Validation"),
    "repair_code": ("GameCodeAgentRepair", "Repair Code"),
    "replan_game_design": ("GameDesignAgentReplan", "Replan Game Design"),
    "gameplay_qa": ("GameplayQAAgent", "Gameplay QA"),
    "gameplay_repair": ("GameplayRepairAgent", "Gameplay Repair"),
    "publish_artifact": ("PublishArtifactAgent", "Publish Artifact"),
    "feedback_understanding": ("FeedbackUnderstandingAgent", "Understand Feedback"),
    "code_revision": ("CodeRevisionAgent", "Revise Existing Code"),
    "revision_repair": ("CodeRevisionRepairAgent", "Repair Revision"),
    "publish_revision": ("PublishRevisionAgent", "Save Preview Version"),
    "memory_update": ("MemoryUpdateAgent", "Update Memory"),
}


class GenerationState(TypedDict, total=False):
    task_id: str
    user_id: str
    use_real: bool
    dimension: str  # "2d" | "3d"
    task_kind: str  # "generation" | "revision"

    status: str
    prompt: str
    normalized_prompt: str
    source_feedback: str
    feedback_brief: str
    retrieved_memories: list
    memory_context: str
    base_game_id: str
    base_version: str
    existing_files: list
    revision_result: dict

    asset_ids: list
    uploaded_assets: list

    safety_result: dict
    game_spec: dict
    expanded_brief: dict
    mechanic_plan: dict
    archetype_result: dict
    asset_manifest: dict
    game_design: dict
    content_plan: dict
    balance_config: dict

    generated_files: list  # [{"path": str, "content": str}]
    validation_result: dict
    gameplay_qa_result: dict
    use_template_code: bool  # replan 兜底：回退到模板 game.js，保证产物可校验

    repair_attempts: int
    replan_attempts: int
    gameplay_repair_attempts: int

    last_error: Optional[str]
    error_code: Optional[str]
    error_message: Optional[str]

    game_id: Optional[str]
    version_id: Optional[str]
    manifest_url: Optional[str]
    preview_url: Optional[str]

    # 流式落库用（非业务状态）：每个节点把展示信息带出来
    _agent: str
    _logs: list
    _tokens_delta: int
