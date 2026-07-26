"""任务域:创建/修订/详情/步骤/日志分页/SSE 增量。"""
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.agent_events import AgentLogEntryOut, AgentLogItemOut
from app.schemas.games import GameDetailOut


class TaskCreateIn(BaseModel):
    idea: str = Field(min_length=1, max_length=2000)
    asset_ids: list[str] = []
    dimension: Literal["2d", "3d"] = "2d"  # 2D Phaser/Vite or 3D WebGL (Three.js)
    task_kind: Literal["generation", "remix"] = "generation"
    source_game_id: str | None = None


class TaskRevisionIn(BaseModel):
    feedback: str = Field(min_length=1, max_length=2000)


class TaskIdOut(BaseModel):
    task_id: str


class TaskRetryOut(TaskIdOut):
    mode: Literal["restart", "resume"]


class TaskStepSummaryOut(BaseModel):
    step: str
    title: str
    status: str
    summary: str | None = None


class DesignFieldOut(BaseModel):
    label: str
    value: str


class DesignPreviewOut(BaseModel):
    title: str
    fields: list[DesignFieldOut]


class TaskAssetOut(BaseModel):
    name: str
    type: str
    status: str
    kind: str | None = None
    scan_status: str | None = None
    url: str | None = None


class TaskGeneratedAssetOut(BaseModel):
    key: str
    name: str
    kind: str
    content_type: str
    bytes: int
    data_url: str
    semantic_ids: list[str] = Field(default_factory=list)
    frame_audit: dict = Field(default_factory=dict)


class TaskGeneratedAssetListOut(BaseModel):
    items: list[TaskGeneratedAssetOut]


class TaskLogPageOut(BaseModel):
    limit: int | None = None
    before: int | None = None
    next_before: int | None = None
    has_more: bool
    total: int
    returned: int


class TaskStepOut(BaseModel):
    seq: int
    agent: str
    name: str
    status: str
    tokens: int | None = None
    attempt: int | None = None
    caused_by_step_id: str | None = None
    contract_version: str | None = None
    contract_hash: str | None = None
    prompt_version: str | None = None
    model: str | None = None
    provider: str | None = None
    input_artifact_ids: list[str] | None = None
    output_artifact_ids: list[str] | None = None
    adopted_plan: Any | None = None
    rejected_plans: Any | None = None
    asset_request_count: int | None = None
    qa_result: Any | None = None
    repair_reason: Any | None = None
    impact_scope: Any | None = None
    latency_ms: int | None = None
    cost_usd: float | None = None
    runtime_consumed: bool | None = None
    logs: list[str]


class TaskOut(BaseModel):
    id: str
    status: str
    current_step: int
    current_agent: str | None = None
    task_kind: str = "generation"
    base_game_id: str | None = None
    base_version: str | None = None
    feedback_text: str | None = None
    feedback_brief: str | None = None
    repair_attempts: int
    replan_attempts: int
    max_repair_attempts: int
    max_replan_attempts: int
    tokens: int
    cost_usd: float | None = None
    error: str | None = None
    error_code: str | None = None
    failed_stage: str | None = None
    idea: str
    dimension: str
    contract_hash: str | None = None
    contract_revision: int | None = None
    created_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    updated_at: str | None = None
    progress: int
    game_title: str
    manifest_url: str | None = None
    preview_url: str | None = None
    step_summaries: list[TaskStepSummaryOut]
    game: GameDetailOut | None = None
    design: DesignPreviewOut | None = None
    design_contract: dict[str, Any] | None = None
    assets: list[TaskAssetOut] | None = None
    logs: list[AgentLogItemOut] | None = None
    steps: list[TaskStepOut] | None = None
    logs_page: TaskLogPageOut | None = None


class TaskLogDeltaOut(BaseModel):
    cursor: int
    step_id: str
    agent_name: str
    step: str
    status: str
    entry: AgentLogEntryOut


class TaskStepStatusPatchOut(BaseModel):
    step_id: str
    agent_name: str
    step: str
    status: str
    duration: str | None = None


class TaskEventDeltaOut(BaseModel):
    cursor: int
    task: TaskOut
    logs: list[TaskLogDeltaOut]
    steps: list[TaskStepStatusPatchOut]


class TaskListOut(BaseModel):
    items: list[TaskOut]
    total: int | None = None
    has_more: bool | None = None
