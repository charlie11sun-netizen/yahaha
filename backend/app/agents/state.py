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
    "gameplay_planning": ("GameplayPlanningAgent", "Gameplay Planning"),
    "archetype_router": ("ArchetypeRouterAgent", "Archetype Router"),
    "asset_processing": ("AssetAgent", "Asset Processing"),
    "asset_generation": ("GameAssetGenerationAgent", "Generate Game Assets"),
    "game_design": ("GameDesignAgent", "Game Design"),
    "content_plan": ("ContentPlanAgent", "Content Plan"),
    "balance_plan": ("BalanceAgent", "Balance Plan"),
    "design_contract": ("DesignContractCompilerAgent", "Design Contract"),
    "contract_gate": ("ContractGateAgent", "Contract Gate"),
    "code_generation": ("GameCodeAgent", "Code Generation"),
    "project_build": ("ProjectBuildAgent", "Project Build"),
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
    "publish_remix": ("PublishRemixAgent", "Save Remix"),
    "memory_update": ("MemoryUpdateAgent", "Update Memory"),
}


class GenerationState(TypedDict, total=False):
    task_id: str
    user_id: str
    use_real: bool
    dimension: str  # "2d" | "3d"
    task_kind: str  # "generation" | "revision" | "remix"
    contract_version: str
    trace_contract_version: str
    prompt_version: str
    model: str
    provider: str

    status: str
    prompt: str
    normalized_prompt: str
    source_feedback: str
    feedback_brief: str
    # Structured judgment emitted by FeedbackUnderstandingAgent.  Revision
    # routing consumes this instead of inferring asset work from UI categories
    # or keyword lists; the deterministic contract diff is retained alongside
    # it as auditable evidence and as a fallback for legacy/offline runs.
    feedback_asset_impact: dict
    retrieved_memory_profiles: list
    retrieved_memories: list
    memory_context: str
    base_game_id: str
    base_version: str
    existing_files: list
    revision_result: dict

    asset_ids: list
    uploaded_assets: list
    generated_assets: list
    asset_trace: list

    safety_result: dict
    game_spec: dict
    expanded_brief: dict
    mechanic_plan: dict
    # Client-side conversation chain gameplay-planning -> game-design ->
    # design-contract: the gateway strips store/previous_response_id, so the
    # raw user/assistant messages are replayed as explicit input items.
    planning_transcript: Optional[list]
    # Provider id of the latest chain member; ledger lineage only, never sent.
    planning_response_id: Optional[str]
    archetype_result: dict
    asset_manifest: dict
    # Semantic sprite contract: design states -> runtime consumers -> atlas
    # frame bindings.  Kept separate from the legacy `assets` list so older
    # clients can still read their manifest unchanged.
    sprite_demand_manifest: dict
    asset_batch_specs: dict
    runtime_consumers: dict
    game_design: dict
    content_plan: dict
    balance_config: dict

    # Frozen design-contract boundary and its read-only derived views.  The
    # original prompt/spec/design remain audit evidence; downstream producers
    # use these fields once the contract gate passes.
    intent_record: dict
    design_contract: dict
    contract_hash: str
    contract_revision: int
    contract_diff: dict
    contract_gate: dict
    contract_error: str
    design_execution_view: dict
    spec_execution_view: dict
    style_bible: dict
    author_role_contracts: dict
    acceptance_plan: dict
    runtime_asset_requirements: dict

    generated_files: list  # [{"path": str, "content": str}]
    project_files: list
    artifact_format: str
    code_source: str  # "author" | "template" | "model" | "revision" —— gameplay QA 用它区分占位是否必须被替换
    build_result: dict
    validation_result: dict
    gameplay_qa_result: dict
    use_template_code: bool  # replan 兜底：回退到模板 game.js，保证产物可校验

    repair_attempts: int
    replan_attempts: int
    gameplay_repair_attempts: int
    # gameplay QA 失败走整包重生成时的失因清单：作者提示词逐条要求解决，
    # code_generation 消费后清空；replan 换设计时也清空
    gameplay_qa_feedback: Optional[list]

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
