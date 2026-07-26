"""Agent 日志事件域:结构化事件联合(discriminator=type)与日志条目。

新事件类型必须同步三处:事件类、AgentLogEventOut 联合、AGENT_LOG_EVENT_TYPES
(serializer 据此丢弃未知类型,防新事件 500 任务端点)。
"""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class AgentBundleFileOut(BaseModel):
    path: str | None = None
    bytes: int | None = None
    lines: int | None = None
    kind: str | None = None
    referenced: bool | None = None


class AgentFileContextOut(BaseModel):
    path: str | None = None
    record_state: str | None = None
    record_source: str | None = None
    bytes: int | None = None
    lines: int | None = None
    deleted: bool | None = None
    updated_at: int | None = None
    cline_read_date: int | None = None
    cline_edit_date: int | None = None


class AgentBundleMetadataOut(BaseModel):
    files: list[AgentBundleFileOut] | None = None
    script_refs: list[str] | None = None
    files_in_context: list[AgentFileContextOut] | None = None


class AgentSearchMatchOut(BaseModel):
    path: str | None = None
    line: int | None = None
    text: str | None = None


class _AgentLogEventBaseOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    seq: int | None = None
    status: str | None = None


class AgentFileChangeEventOut(_AgentLogEventBaseOut):
    type: Literal["file_change"]
    action: Literal["created", "modified", "deleted"] | None = None
    path: str | None = None
    added: int | None = None
    deleted: int | None = None
    bytes: int | None = None
    chunks: int | None = None
    detail: str | None = None
    diff: str | None = None
    diff_format: Literal["unified", "omitted_large", "empty"] | None = None
    cline_tool: str | None = None
    files_in_context: list[AgentFileContextOut] | None = None
    tool: str | None = None


class AgentTurnStateEventOut(_AgentLogEventBaseOut):
    type: Literal["turn_state"]
    phase: str | None = None
    message: str | None = None
    source: str | None = None
    reason: str | None = None
    agent: str | None = None
    tool_count: int | None = None
    bundle: AgentBundleMetadataOut | None = None
    checks_ok: bool | None = None
    changed: list[str] | None = None


class AgentHeartbeatEventOut(_AgentLogEventBaseOut):
    type: Literal["heartbeat"]
    agent: str | None = None
    operation: Literal["authoring", "repairing"] | None = None
    phase: str | None = None
    elapsed_seconds: int | None = None
    idle_seconds: int | None = None
    file_count: int | None = None
    changed_count: int | None = None
    checks: str | None = None
    files_in_context: list[AgentFileContextOut] | None = None


class AgentCheckEventOut(_AgentLogEventBaseOut):
    type: Literal["check"]
    tool: str | None = None
    static_ok: bool | None = None
    static_errors: int | None = None
    smoke_ok: bool | None = None
    checks_ok: bool | None = None
    bundle: AgentBundleMetadataOut | None = None


class AgentToolEventOut(_AgentLogEventBaseOut):
    type: Literal["tool"]
    tool: str | None = None
    cline_tool: str | None = None
    path: str | None = None
    name: str | None = None
    bytes: int | None = None
    query: str | None = None
    file_pattern: str | None = None
    files: list[AgentBundleFileOut] | None = None
    script_refs: list[str] | None = None
    files_in_context: list[AgentFileContextOut] | None = None
    matches: list[AgentSearchMatchOut] | None = None


class AgentUsageEventOut(_AgentLogEventBaseOut):
    type: Literal["usage"]
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    cached_tokens: int | None = None
    cache_write_tokens: int | None = None
    requests: int | None = None
    cache_percent: int | None = None


class AgentUsageProgressEventOut(_AgentLogEventBaseOut):
    type: Literal["usage_progress"]
    agent: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    cached_tokens: int | None = None
    cache_write_tokens: int | None = None


class AgentErrorEventOut(_AgentLogEventBaseOut):
    type: Literal["error"]
    message: str | None = None
    source: str | None = None


class AgentNoticeEventOut(_AgentLogEventBaseOut):
    type: Literal["notice"]
    message: str | None = None
    reason: str | None = None


class AgentRoleBudgetExhaustedEventOut(_AgentLogEventBaseOut):
    type: Literal["role_budget_exhausted"]
    agent: str
    operation: Literal["authoring", "repairing"]
    reason: Literal["max_turns"] = "max_turns"
    message: str | None = None
    turns_limit: int | None = None
    changed: list[str] | None = None
    checks_ok: bool | None = None


class AgentRepairAttemptStartedEventOut(_AgentLogEventBaseOut):
    type: Literal["repair_attempt_started"]
    agent: str | None = None
    operation: Literal["repairing"] = "repairing"
    repair_kind: Literal["build", "revision", "gameplay"] | None = None
    attempt: int | None = None
    max_attempts: int | None = None
    caused_by_step_id: str | None = None


class AgentAuthorTeamEventOut(_AgentLogEventBaseOut):
    type: Literal["author_team"]
    phase: str | None = None
    role: str | None = None
    message: str | None = None
    base_revision: str | None = None
    contract_hash: str | None = None
    contract_source: str | None = None


class AgentPatchDiagnosticOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    code: str | None = None
    path: str | None = None
    line: int | None = None
    column: int | None = None
    rule: str | None = None
    message: str | None = None


class AgentValidationRejectionEventOut(_AgentLogEventBaseOut):
    type: Literal["validation_rejection"]
    tool: str | None = None
    path: str | None = None
    diagnostics: list[AgentPatchDiagnosticOut] | None = None
    diagnostics_omitted: int | None = None


class AgentRetryEventOut(_AgentLogEventBaseOut):
    type: Literal["retry"]
    source: str | None = None
    attempt: int | None = None
    next_attempt: int | None = None
    reason: str | None = None
    stream_event: str | None = None
    error_code: str | None = None
    response_id: str | None = None
    delay_seconds: float | None = None


class AgentRoleStreamFailedPartialEventOut(_AgentLogEventBaseOut):
    type: Literal["role_stream_failed_partial"]
    agent: str | None = None
    operation: Literal["authoring", "repairing"] | None = None
    reason: str | None = None
    message: str | None = None
    changed: list[str] | None = None
    checks_ok: bool | None = None


AgentLogEventOut = Annotated[
    AgentFileChangeEventOut
    | AgentTurnStateEventOut
    | AgentHeartbeatEventOut
    | AgentCheckEventOut
    | AgentToolEventOut
    | AgentUsageEventOut
    | AgentUsageProgressEventOut
    | AgentErrorEventOut
    | AgentNoticeEventOut
    | AgentRoleBudgetExhaustedEventOut
    | AgentRepairAttemptStartedEventOut
    | AgentAuthorTeamEventOut
    | AgentValidationRejectionEventOut
    | AgentRetryEventOut
    | AgentRoleStreamFailedPartialEventOut,
    Field(discriminator="type"),
]

# Single source of truth for serializers: payloads whose type is not listed
# here must be dropped before response validation, never allowed to 500 the
# task endpoints when an agent starts emitting a new event type.
AGENT_LOG_EVENT_TYPES = frozenset(
    {
        "file_change",
        "turn_state",
        "heartbeat",
        "check",
        "tool",
        "usage",
        "usage_progress",
        "error",
        "notice",
        "role_budget_exhausted",
        "repair_attempt_started",
        "author_team",
        "validation_rejection",
        "retry",
        "role_stream_failed_partial",
    }
)


class AgentLogEntryOut(BaseModel):
    cursor: int | None = None
    line: str
    level: str | None = None
    created_at: str | None = None
    event: AgentLogEventOut | None = None


class AgentLogItemOut(BaseModel):
    step_id: str | None = None
    agent_name: str
    step: str
    message: str
    created_at: str | None = None
    duration: str | None = None
    status: str
    lines: list[str]
    entries: list[AgentLogEntryOut] | None = None
