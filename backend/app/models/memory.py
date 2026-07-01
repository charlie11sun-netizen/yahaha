from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.common import PkMixin, TimestampMixin, now_utc
from app.db.base import Base


class MemoryScope:
    USER = "user"
    GAME = "game"
    TASK = "task"


class MemoryCategory:
    STYLE = "style"
    MECHANICS = "mechanics"
    CONTROLS = "controls"
    DIFFICULTY = "difficulty"
    CONTENT = "content"
    CONSTRAINTS = "constraints"
    FEEDBACK = "feedback"


class MemorySource:
    IDEA = "idea"
    FEEDBACK = "feedback"
    MANUAL = "manual"
    PUBLISH = "publish"
    SYSTEM = "system"


class MemoryStatus:
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    DELETED = "deleted"


class MemoryProfileStatus:
    ACTIVE = "active"
    CANDIDATE = "candidate"
    SUPERSEDED = "superseded"
    DELETED = "deleted"


class MemoryExplicitness:
    MANUAL = "manual"
    EXPLICIT = "explicit"
    INFERRED = "inferred"


class MemoryProfileOperation:
    CREATED = "created"
    CANDIDATE = "candidate"
    REINFORCED = "reinforced"
    AUTO_PROMOTED = "auto_promoted"
    SUPERSEDED = "superseded"
    CORRECTED = "corrected"
    UTILITY_UPDATED = "utility_updated"
    EXPIRED = "expired"
    DELETED = "deleted"


class MemoryItem(PkMixin, TimestampMixin, Base):
    __tablename__ = "memory_items"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    scope_type: Mapped[str] = mapped_column(String(20), default=MemoryScope.USER, index=True)
    scope_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    category: Mapped[str] = mapped_column(String(40), default=MemoryCategory.FEEDBACK, index=True)
    raw_text: Mapped[str] = mapped_column(Text)
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_type: Mapped[str] = mapped_column(String(40), default=MemorySource.MANUAL, index=True)
    source_task_id: Mapped[str | None] = mapped_column(
        ForeignKey("generation_tasks.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source_game_id: Mapped[str | None] = mapped_column(
        ForeignKey("games.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    importance: Mapped[int] = mapped_column(Integer, default=3)
    confidence: Mapped[float] = mapped_column(Numeric(4, 3), default=1.0)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    status: Mapped[str] = mapped_column(String(20), default=MemoryStatus.ACTIVE, index=True)
    supersedes_id: Mapped[str | None] = mapped_column(
        ForeignKey("memory_items.id", ondelete="SET NULL"), nullable=True
    )
    embedding: Mapped[list[float] | None] = mapped_column(JSON, nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    embedding_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class MemorySettings(Base):
    __tablename__ = "memory_settings"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    allow_cross_game_memory: Mapped[bool] = mapped_column(Boolean, default=True)
    allow_memory_extraction: Mapped[bool] = mapped_column(Boolean, default=True)
    retention_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class MemoryProfile(PkMixin, TimestampMixin, Base):
    __tablename__ = "memory_profiles"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    scope_type: Mapped[str] = mapped_column(String(20), index=True)
    scope_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    profile_key: Mapped[str] = mapped_column(String(160), index=True)
    category: Mapped[str] = mapped_column(String(40), index=True)
    value_text: Mapped[str] = mapped_column(Text)
    summary_text: Mapped[str] = mapped_column(Text)
    evidence_span: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Numeric(4, 3), default=0.8)
    scope_confidence: Mapped[float] = mapped_column(Numeric(4, 3), default=0.8)
    explicitness: Mapped[str] = mapped_column(String(20), default=MemoryExplicitness.INFERRED)
    status: Mapped[str] = mapped_column(String(20), default=MemoryProfileStatus.ACTIVE, index=True)
    source_memory_id: Mapped[str] = mapped_column(
        ForeignKey("memory_items.id", ondelete="CASCADE"), index=True
    )
    conflicts_with_id: Mapped[str | None] = mapped_column(
        ForeignKey("memory_profiles.id", ondelete="SET NULL"), nullable=True, index=True
    )
    support_count: Mapped[int] = mapped_column(Integer, default=1)
    utility_score: Mapped[float] = mapped_column(Numeric(4, 3), default=0.5)
    utility_observation_count: Mapped[int] = mapped_column(Integer, default=0)
    last_supported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class MemoryProfileVersion(PkMixin, TimestampMixin, Base):
    __tablename__ = "memory_profile_versions"

    profile_id: Mapped[str] = mapped_column(
        ForeignKey("memory_profiles.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    operation: Mapped[str] = mapped_column(String(30), index=True)
    snapshot_json: Mapped[dict] = mapped_column(JSON)
    source_memory_id: Mapped[str | None] = mapped_column(
        ForeignKey("memory_items.id", ondelete="SET NULL"), nullable=True, index=True
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
