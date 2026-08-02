"""记忆域:原始记忆/设置/Profile 及其历史。"""
from typing import Any, Literal

from pydantic import BaseModel, Field


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
