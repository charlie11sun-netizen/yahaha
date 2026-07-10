"""replace generation snapshot column with LangGraph checkpoints

Revision ID: 0009_langgraph_checkpoints
Revises: 0008_generation_dispatch_outbox
Create Date: 2026-07-10
"""

from alembic import op
import sqlalchemy as sa


revision = "0009_langgraph_checkpoints"
down_revision = "0008_generation_dispatch_outbox"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # PostgresSaver owns and migrates its checkpoint_* tables via setup().
    # Existing manual snapshots cannot be imported safely because they lack
    # LangGraph channel/version metadata; affected failed tasks restart once.
    with op.batch_alter_table("generation_tasks") as batch_op:
        batch_op.drop_column("state_json")


def downgrade() -> None:
    with op.batch_alter_table("generation_tasks") as batch_op:
        batch_op.add_column(sa.Column("state_json", sa.Text(), nullable=True))
