from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.common import AssetKind, PkMixin, StepStatus, TaskStatus, TimestampMixin, now_utc

task_assets = Table(
    "task_assets",
    Base.metadata,
    Column("task_id", ForeignKey("generation_tasks.id", ondelete="CASCADE"), primary_key=True),
    Column("asset_id", ForeignKey("assets.id", ondelete="CASCADE"), primary_key=True),
)


class Asset(PkMixin, TimestampMixin, Base):
    __tablename__ = "assets"

    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(120), default="application/octet-stream")
    kind: Mapped[str] = mapped_column(String(20), default=AssetKind.FILE)
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    oss_key: Mapped[str] = mapped_column(String(400))
    scan_status: Mapped[str] = mapped_column(String(20), default="skipped")


class GenerationTask(PkMixin, TimestampMixin, Base):
    __tablename__ = "generation_tasks"
    __table_args__ = (Index("ix_generation_tasks_user_id_status", "user_id", "status"),)

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    idea: Mapped[str] = mapped_column(Text)
    task_kind: Mapped[str] = mapped_column(String(20), default="generation", server_default="generation")
    base_game_id: Mapped[str | None] = mapped_column(
        ForeignKey("games.id", ondelete="SET NULL"), nullable=True, index=True
    )
    base_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    feedback_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    feedback_brief: Mapped[str | None] = mapped_column(Text, nullable=True)
    dimension: Mapped[str] = mapped_column(String(8), default="2d", server_default="2d")  # 2d | 3d
    status: Mapped[str] = mapped_column(String(20), default=TaskStatus.PENDING, index=True)
    dispatch_generation: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    current_step: Mapped[int] = mapped_column(Integer, default=0)
    current_agent: Mapped[str | None] = mapped_column(String(40), nullable=True)
    result_game_id: Mapped[str | None] = mapped_column(
        ForeignKey("games.id", ondelete="SET NULL"), nullable=True
    )
    version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    tokens_used: Mapped[int] = mapped_column(BigInteger, default=0)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    failed_stage: Mapped[str | None] = mapped_column(String(80), nullable=True)
    repair_attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_repair_attempts: Mapped[int] = mapped_column(Integer, default=2)
    replan_attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_replan_attempts: Mapped[int] = mapped_column(Integer, default=1)
    spec_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    design_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    steps: Mapped[list["AgentStep"]] = relationship(
        back_populates="task", cascade="all, delete-orphan", lazy="selectin", order_by="AgentStep.seq"
    )
    assets: Mapped[list["Asset"]] = relationship("Asset", secondary=task_assets, lazy="selectin")
    result_game = relationship("Game", lazy="joined", foreign_keys=[result_game_id])


class GenerationDispatchOutbox(PkMixin, TimestampMixin, Base):
    __tablename__ = "generation_dispatch_outbox"
    __table_args__ = (
        UniqueConstraint(
            "task_id",
            "dispatch_generation",
            name="uq_generation_dispatch_task_generation",
        ),
        Index(
            "ix_generation_dispatch_outbox_ready",
            "published_at",
            "available_at",
            "created_at",
        ),
    )

    task_id: Mapped[str] = mapped_column(ForeignKey("generation_tasks.id", ondelete="CASCADE"))
    dispatch_generation: Mapped[int] = mapped_column(Integer)
    request_id: Mapped[str] = mapped_column(String(128), default="", server_default="")
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class AgentStep(PkMixin, TimestampMixin, Base):
    __tablename__ = "agent_steps"

    task_id: Mapped[str] = mapped_column(ForeignKey("generation_tasks.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    agent: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default=StepStatus.PENDING)
    tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    caused_by_step_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    task: Mapped["GenerationTask"] = relationship(back_populates="steps")
    logs: Mapped[list["AgentLog"]] = relationship(
        back_populates="step", cascade="all, delete-orphan", lazy="selectin", order_by="AgentLog.seq"
    )


class AgentLog(Base):
    __tablename__ = "agent_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    step_id: Mapped[str] = mapped_column(ForeignKey("agent_steps.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer, default=0)
    line: Mapped[str] = mapped_column(Text)
    level: Mapped[str] = mapped_column(String(10), default="info")
    payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    step: Mapped["AgentStep"] = relationship(back_populates="logs")


class AgentTraceEvent(PkMixin, TimestampMixin, Base):
    """Opt-in full-fidelity code-agent trace; never included in normal task DTOs."""

    __tablename__ = "agent_trace_events"
    __table_args__ = (
        Index("ix_agent_trace_events_step_id_seq", "step_id", "seq"),
        Index("ix_agent_trace_events_task_id_created_at", "task_id", "created_at"),
        Index("ix_agent_trace_events_run_id_seq", "run_id", "seq"),
    )

    task_id: Mapped[str] = mapped_column(
        ForeignKey("generation_tasks.id", ondelete="CASCADE"), index=False
    )
    step_id: Mapped[str] = mapped_column(
        ForeignKey("agent_steps.id", ondelete="CASCADE"), index=False
    )
    run_id: Mapped[str] = mapped_column(String(36))
    seq: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(32))
    event_type: Mapped[str] = mapped_column(String(40))
    agent: Mapped[str] = mapped_column(String(120))
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    payload_json: Mapped[str] = mapped_column(Text)
    payload_chars: Mapped[int] = mapped_column(BigInteger, default=0)


class LLMCall(PkMixin, TimestampMixin, Base):
    __tablename__ = "llm_calls"

    task_id: Mapped[str | None] = mapped_column(
        ForeignKey("generation_tasks.id", ondelete="SET NULL"), nullable=True, index=True
    )
    step_id: Mapped[str | None] = mapped_column(
        ForeignKey("agent_steps.id", ondelete="SET NULL"), nullable=True, index=True
    )
    model: Mapped[str] = mapped_column(String(120))
    prompt_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    completion_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    total_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    # prompt_tokens 中命中 prompt cache 的部分（provider 侧折价读取）。
    cached_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    retried: Mapped[bool] = mapped_column(Boolean, default=False)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
