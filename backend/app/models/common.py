import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column


def gen_uuid() -> str:
    return str(uuid.uuid4())


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class PkMixin:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


# ---- 状态常量（用字符串列 + 常量，便于 create_all，无需 DB enum 迁移）----
class GameStatus:
    DRAFT = "draft"
    PREVIEW = "preview"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class TaskStatus:
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class StepStatus:
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class GameSource:
    SEED = "seed"
    CREATE = "create"


class AssetKind:
    IMAGE = "image"
    VIDEO = "video"
    FILE = "file"
