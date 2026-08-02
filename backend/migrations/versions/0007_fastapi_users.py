"""fastapi-users account fields

Revision ID: 0007_fastapi_users
Revises: 0006_agent_log_payload
Create Date: 2026-07-08
"""

from alembic import op
import sqlalchemy as sa


revision = "0007_fastapi_users"
down_revision = "0006_agent_log_payload"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("is_superuser", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column("is_verified", sa.Boolean(), nullable=False, server_default=sa.false()))

    with op.batch_alter_table("oauth_accounts") as batch_op:
        batch_op.add_column(sa.Column("access_token", sa.Text(), nullable=False, server_default=""))
        batch_op.add_column(sa.Column("expires_at", sa.BigInteger(), nullable=True))
        batch_op.add_column(sa.Column("refresh_token", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("oauth_accounts") as batch_op:
        batch_op.drop_column("refresh_token")
        batch_op.drop_column("expires_at")
        batch_op.drop_column("access_token")

    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("is_verified")
        batch_op.drop_column("is_superuser")
