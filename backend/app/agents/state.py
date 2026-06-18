"""LangGraph 共享状态与步骤常量（对应 docs/multi-agent_design.md §5）。"""
from typing import Any, Optional, TypedDict

MAX_REPAIR = 2
MAX_REPLAN = 1

# step -> (agent_name, 展示名)
STEP_META: dict[str, tuple[str, str]] = {
    "safety_intake": ("SafetyIntakeAgent", "Safety Intake"),
    "intent_spec": ("IntentSpecAgent", "Intent Spec"),
    "asset_processing": ("AssetAgent", "Asset Processing"),
    "game_design": ("GameDesignAgent", "Game Design"),
    "code_generation": ("GameCodeAgent", "Code Generation"),
    "build_validation": ("BuildValidateAgent", "Build Validation"),
    "repair_code": ("GameCodeAgentRepair", "Repair Code"),
    "replan_game_design": ("GameDesignAgentReplan", "Replan Game Design"),
    "publish_artifact": ("PublishArtifactAgent", "Publish Artifact"),
}


class GenerationState(TypedDict, total=False):
    task_id: str
    user_id: str
    use_real: bool

    status: str
    prompt: str
    normalized_prompt: str

    asset_ids: list
    uploaded_assets: list

    safety_result: dict
    game_spec: dict
    asset_manifest: dict
    game_design: dict

    generated_files: list  # [{"path": str, "content": str}]
    validation_result: dict
    use_template_code: bool  # replan 兜底：回退到模板 game.js，保证产物可校验

    repair_attempts: int
    replan_attempts: int

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
