"""initial baseline schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-19

基线迁移：对全新库一次性建好当前全部表（与 Base.metadata 对齐）。
后续 schema 变更请用 `alembic revision --autogenerate -m "..."` 生成增量迁移。
"""
from alembic import op

import app.models  # noqa: F401  注册所有表到 Base.metadata
from app.db.base import Base

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
