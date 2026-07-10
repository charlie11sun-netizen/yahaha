"""transactional generation dispatch outbox

Revision ID: 0008_generation_dispatch_outbox
Revises: 0007_fastapi_users
Create Date: 2026-07-09
"""

from datetime import datetime, timezone
import uuid

from alembic import op
import sqlalchemy as sa


revision = "0008_generation_dispatch_outbox"
down_revision = "0007_fastapi_users"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("generation_tasks") as batch_op:
        batch_op.add_column(
            sa.Column(
                "dispatch_generation",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            )
        )

    op.create_table(
        "generation_dispatch_outbox",
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("dispatch_generation", sa.Integer(), nullable=False),
        sa.Column(
            "request_id", sa.String(length=128), nullable=False, server_default=""
        ),
        sa.Column(
            "attempts", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["task_id"], ["generation_tasks.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "task_id",
            "dispatch_generation",
            name="uq_generation_dispatch_task_generation",
        ),
    )
    op.create_index(
        "ix_generation_dispatch_outbox_ready",
        "generation_dispatch_outbox",
        ["published_at", "available_at", "created_at"],
        unique=False,
    )

    # Pending tasks may have been committed while their broker publish failed.
    # Move them to a fresh generation and create a durable unpublished event.
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # Set-based SQL also keeps `alembic upgrade --sql` usable for production
        # change review; PostgreSQL 16 provides gen_random_uuid() natively.
        op.execute(
            sa.text(
                """
                INSERT INTO generation_dispatch_outbox (
                    task_id, dispatch_generation, request_id, attempts,
                    available_at, last_attempt_at, published_at, last_error,
                    id, created_at
                )
                SELECT
                    id, 1, 'migration:' || id, 0,
                    CURRENT_TIMESTAMP, NULL, NULL, NULL,
                    CAST(gen_random_uuid() AS VARCHAR(36)), CURRENT_TIMESTAMP
                FROM generation_tasks
                WHERE status = 'pending'
                """
            )
        )
        op.execute(
            sa.text(
                """
                UPDATE generation_tasks
                SET dispatch_generation = 1
                WHERE status = 'pending'
                """
            )
        )
        return

    tasks = sa.table(
        "generation_tasks",
        sa.column("id", sa.String(length=36)),
        sa.column("status", sa.String(length=20)),
        sa.column("dispatch_generation", sa.Integer()),
    )
    pending_ids = [
        row.id
        for row in bind.execute(
            sa.select(tasks.c.id).where(tasks.c.status == "pending")
        )
    ]
    for offset in range(0, len(pending_ids), 500):
        task_ids = pending_ids[offset : offset + 500]
        bind.execute(
            tasks.update().where(tasks.c.id.in_(task_ids)).values(dispatch_generation=1)
        )
        now = datetime.now(timezone.utc)
        outbox = sa.table(
            "generation_dispatch_outbox",
            sa.column("task_id", sa.String(length=36)),
            sa.column("dispatch_generation", sa.Integer()),
            sa.column("request_id", sa.String(length=128)),
            sa.column("attempts", sa.Integer()),
            sa.column("available_at", sa.DateTime(timezone=True)),
            sa.column("last_attempt_at", sa.DateTime(timezone=True)),
            sa.column("published_at", sa.DateTime(timezone=True)),
            sa.column("last_error", sa.Text()),
            sa.column("id", sa.String(length=36)),
            sa.column("created_at", sa.DateTime(timezone=True)),
        )
        rows = []
        for task_id in task_ids:
            event_id = str(uuid.uuid4())
            rows.append(
                {
                    "task_id": task_id,
                    "dispatch_generation": 1,
                    "request_id": f"migration:{event_id}",
                    "attempts": 0,
                    "available_at": now,
                    "last_attempt_at": None,
                    "published_at": None,
                    "last_error": None,
                    "id": event_id,
                    "created_at": now,
                }
            )
        op.bulk_insert(outbox, rows)


def downgrade() -> None:
    op.drop_index(
        "ix_generation_dispatch_outbox_ready", table_name="generation_dispatch_outbox"
    )
    op.drop_table("generation_dispatch_outbox")
    with op.batch_alter_table("generation_tasks") as batch_op:
        batch_op.drop_column("dispatch_generation")
