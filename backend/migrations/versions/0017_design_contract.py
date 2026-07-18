"""persist frozen DesignContract snapshots and hashes

Revision ID: 0017_design_contract
Revises: 0016_decision_chain_trace
Create Date: 2026-07-18
"""

from alembic import context, op
import sqlalchemy as sa


revision = "0017_design_contract"
down_revision = "0016_decision_chain_trace"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    existing = set() if context.is_offline_mode() else {column["name"] for column in sa.inspect(bind).get_columns("generation_tasks")}
    columns = {
        "contract_json": sa.Text(),
        "contract_hash": sa.String(length=64),
        "contract_revision": sa.Integer(),
    }
    for name, column_type in columns.items():
        if name not in existing:
            op.add_column("generation_tasks", sa.Column(name, column_type, nullable=True))
    indexes = set() if context.is_offline_mode() else {index["name"] for index in sa.inspect(bind).get_indexes("generation_tasks")}
    if "ix_generation_tasks_contract_hash" not in indexes:
        op.create_index("ix_generation_tasks_contract_hash", "generation_tasks", ["contract_hash"], unique=False)
    step_existing = set() if context.is_offline_mode() else {column["name"] for column in sa.inspect(bind).get_columns("agent_steps")}
    if "contract_hash" not in step_existing:
        op.add_column("agent_steps", sa.Column("contract_hash", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_index("ix_generation_tasks_contract_hash", table_name="generation_tasks")
    op.drop_column("generation_tasks", "contract_revision")
    op.drop_column("generation_tasks", "contract_hash")
    op.drop_column("generation_tasks", "contract_json")
    op.drop_column("agent_steps", "contract_hash")
