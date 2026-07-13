"""请求体 Schema（响应统一用 services/serialize.py 输出 dict）。"""
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi_users import schemas as fastapi_users_schemas
from pydantic import BaseModel, ConfigDict, EmailStr, Field


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)
    display_name: str = Field(min_length=1, max_length=120)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class ProfileUpdateIn(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    email: EmailStr | None = None
    avatar: str | None = Field(default=None, max_length=8)


class ChangePasswordIn(BaseModel):
    current_password: str = ""
    new_password: str = Field(min_length=6)


class GameUpdateIn(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    summary: str | None = Field(default=None, max_length=2000)
    tags: list[str] | None = None


class CommentIn(BaseModel):
    body: str = Field(min_length=1, max_length=2000)


class ScoreIn(BaseModel):
    points: int = Field(ge=0, le=100_000_000)
    player_name: str | None = Field(default=None, max_length=80)


class TaskCreateIn(BaseModel):
    idea: str = Field(min_length=1, max_length=2000)
    asset_ids: list[str] = []
    dimension: Literal["2d", "3d"] = "2d"  # 2D Phaser/Vite or 3D WebGL (Three.js)
    task_kind: Literal["generation", "remix"] = "generation"
    source_game_id: str | None = None


class TaskRevisionIn(BaseModel):
    feedback: str = Field(min_length=1, max_length=2000)


class OkOut(BaseModel):
    ok: bool


class TaskIdOut(BaseModel):
    task_id: str


class TaskRetryOut(TaskIdOut):
    mode: Literal["restart", "resume"]


class GameCardOut(BaseModel):
    id: str
    title: str
    summary: str
    genre: str
    cover: str | None = None
    version: str
    source: str
    from_create: bool
    status: str
    author: str
    author_init: str
    author_id: str
    tags: list[str]
    plays: int
    plays_str: str
    likes: int
    likes_str: str
    published_at: str | None = None
    date: str
    manifest_url: str
    oss_path: str
    remixed_from_game_id: str | None = None
    remixed_from_version: str | None = None


class RemixedFromOut(BaseModel):
    id: str
    title: str
    author: str
    version: str | None = None


class GameDetailOut(GameCardOut):
    prompt: str | None = None
    bundle_url: str
    liked: bool | None = None
    favorited: bool | None = None
    remixed_from: RemixedFromOut | None = None
    remix_count: int | None = None


class GameListOut(BaseModel):
    items: list[GameCardOut]
    total: int
    has_more: bool


class GameCollectionOut(BaseModel):
    items: list[GameCardOut]
    total: int | None = None
    has_more: bool | None = None


class GameStatsOut(BaseModel):
    game_count: int
    total_plays: int


class TagsOut(BaseModel):
    tags: list[str]


class GameVersionOut(BaseModel):
    version: str
    created_at: str | None = None
    size_bytes: int | None = None
    sha256: str | None = None
    is_current: bool


class GameVersionListOut(BaseModel):
    items: list[GameVersionOut]


class PlayOut(BaseModel):
    plays: int
    plays_str: str
    counted: bool


class LikeOut(BaseModel):
    liked: bool
    likes: int


class FavoriteOut(BaseModel):
    favorited: bool


class CommentOut(BaseModel):
    id: str
    body: str
    created_at: str | None = None
    ago: str
    author: str
    author_init: str
    author_id: str


class CommentListOut(BaseModel):
    items: list[CommentOut]


class ScoreOut(BaseModel):
    rank: int | None = None
    name: str
    points: int
    ago: str


class LeaderboardOut(BaseModel):
    items: list[ScoreOut]


class GameManifestFileOut(BaseModel):
    path: str
    url: str | None = None
    sha256: str | None = None


class GameManifestOut(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    schema_version: str | None = None
    game_id: str | None = None
    version_id: str | None = None
    title: str | None = None
    entry: str | None = None
    entry_url: str | None = None
    runtime: str | None = None
    sha256: str | None = None
    size: int | None = None
    files: list[GameManifestFileOut] | None = None
    assets: list[dict[str, Any]] | None = None
    permissions: dict[str, Any] | None = None
    source: str | None = Field(default=None, alias="_source")
    url: str | None = Field(default=None, alias="_url")


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


class TaskGeneratedAssetListOut(BaseModel):
    items: list[TaskGeneratedAssetOut]


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
    requests: int | None = None
    cache_percent: int | None = None


class AgentErrorEventOut(_AgentLogEventBaseOut):
    type: Literal["error"]
    message: str | None = None
    source: str | None = None


class AgentNoticeEventOut(_AgentLogEventBaseOut):
    type: Literal["notice"]
    message: str | None = None
    reason: str | None = None


AgentLogEventOut = Annotated[
    AgentFileChangeEventOut
    | AgentTurnStateEventOut
    | AgentHeartbeatEventOut
    | AgentCheckEventOut
    | AgentToolEventOut
    | AgentUsageEventOut
    | AgentErrorEventOut
    | AgentNoticeEventOut,
    Field(discriminator="type"),
]


class AgentLogEntryOut(BaseModel):
    line: str
    level: str | None = None
    created_at: str | None = None
    event: AgentLogEventOut | None = None


class AgentLogItemOut(BaseModel):
    agent_name: str
    step: str
    message: str
    created_at: str | None = None
    duration: str | None = None
    status: str
    lines: list[str]
    entries: list[AgentLogEntryOut] | None = None


class TaskStepOut(BaseModel):
    seq: int
    agent: str
    name: str
    status: str
    tokens: int | None = None
    attempt: int | None = None
    caused_by_step_id: str | None = None
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
    assets: list[TaskAssetOut] | None = None
    logs: list[AgentLogItemOut] | None = None
    steps: list[TaskStepOut] | None = None


class TaskListOut(BaseModel):
    items: list[TaskOut]
    total: int | None = None
    has_more: bool | None = None


MemoryScopeLiteral = Literal["user", "game", "task"]
MemoryCategoryLiteral = Literal[
    "style", "mechanics", "controls", "difficulty", "content", "constraints", "feedback"
]


class MemoryCreateIn(BaseModel):
    scope_type: MemoryScopeLiteral = "user"
    scope_id: str | None = None
    category: MemoryCategoryLiteral = "feedback"
    raw_text: str = Field(min_length=1, max_length=4000)
    extracted_text: str | None = Field(default=None, max_length=4000)
    importance: int = Field(default=3, ge=1, le=5)
    pinned: bool = False


class MemoryUpdateIn(BaseModel):
    category: MemoryCategoryLiteral | None = None
    raw_text: str | None = Field(default=None, min_length=1, max_length=4000)
    extracted_text: str | None = Field(default=None, max_length=4000)
    importance: int | None = Field(default=None, ge=1, le=5)
    pinned: bool | None = None
    status: Literal["active", "superseded", "deleted"] | None = None


class MemorySettingsIn(BaseModel):
    enabled: bool | None = None
    allow_cross_game_memory: bool | None = None
    allow_memory_extraction: bool | None = None
    retention_days: int | None = Field(default=None, ge=1, le=3650)


class MemoryProfileUpdateIn(BaseModel):
    value_text: str | None = Field(default=None, min_length=1, max_length=500)
    summary_text: str | None = Field(default=None, min_length=1, max_length=1000)


class UserOut(BaseModel):
    id: str
    name: str
    email: EmailStr
    init: str
    created_at: str | None = None


class FastAPIUserRead(fastapi_users_schemas.BaseUser[str]):
    display_name: str
    avatar_initial: str
    name: str
    init: str
    created_at: datetime | None = None


class FastAPIUserCreate(fastapi_users_schemas.BaseUserCreate):
    display_name: str = Field(min_length=1, max_length=120)
    avatar: str | None = Field(default=None, max_length=8)


class FastAPIUserUpdate(fastapi_users_schemas.BaseUserUpdate):
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    avatar: str | None = Field(default=None, max_length=8)


class AuthOut(BaseModel):
    user: UserOut


class OAuthDemoOut(AuthOut):
    mock: bool


class OAuthProvidersOut(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    google: bool | None = None
    github: bool | None = None
    demo: bool = Field(alias="_demo")


class PublicUserProfileOut(BaseModel):
    id: str
    name: str
    init: str
    game_count: int
    total_plays: int
    followers: int
    following: int
    is_following: bool
    is_self: bool


class FollowOut(BaseModel):
    following: bool


class UploadedAssetOut(BaseModel):
    id: str
    name: str
    kind: str
    size: int
    scan_status: str | None = None
    url: str | None = None


class UploadOut(BaseModel):
    assets: list[UploadedAssetOut]


class MemorySettingsOut(BaseModel):
    enabled: bool
    allow_cross_game_memory: bool
    allow_memory_extraction: bool
    retention_days: int | None = None
    created_at: str | None = None
    updated_at: str | None = None


class MemoryItemOut(BaseModel):
    id: str
    user_id: str
    scope_type: str
    scope_id: str | None = None
    category: str
    raw_text: str
    extracted_text: str | None = None
    source_type: str
    source_task_id: str | None = None
    source_game_id: str | None = None
    source_version: str | None = None
    importance: int
    confidence: float
    pinned: bool
    status: str
    supersedes_id: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class MemoryListOut(BaseModel):
    items: list[MemoryItemOut]


class MemoryProfileOut(BaseModel):
    id: str
    user_id: str
    scope_type: str
    scope_id: str | None = None
    profile_key: str
    category: str
    value_text: str
    summary_text: str
    evidence_span: str
    confidence: float
    scope_confidence: float
    explicitness: str
    status: str
    source_memory_id: str
    conflicts_with_id: str | None = None
    support_count: int
    utility_score: float
    utility_observation_count: int
    last_supported_at: str | None = None
    expires_at: str | None = None
    version: int
    created_at: str | None = None
    updated_at: str | None = None


class MemoryProfileListOut(BaseModel):
    items: list[MemoryProfileOut]


class MemoryProfileVersionOut(BaseModel):
    id: str
    profile_id: str
    version: int
    operation: str
    snapshot: dict[str, Any]
    source_memory_id: str | None = None
    reason: str | None = None
    created_at: str | None = None


class MemoryProfileHistoryOut(BaseModel):
    items: list[MemoryProfileVersionOut]
