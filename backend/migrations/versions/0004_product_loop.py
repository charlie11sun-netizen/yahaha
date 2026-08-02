"""product loop: versions and remix provenance

Revision ID: 0004_product_loop
Revises: 0003_observability_cost
Create Date: 2026-07-03
"""

from alembic import op
import sqlalchemy as sa


revision = "0004_product_loop"
down_revision = "0003_observability_cost"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("games") as batch_op:
        batch_op.add_column(sa.Column("remixed_from_game_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("remixed_from_version", sa.String(length=20), nullable=True))
        batch_op.create_index(
            batch_op.f("ix_games_remixed_from_game_id"),
            ["remixed_from_game_id"],
            unique=False,
        )
        batch_op.create_foreign_key(
            batch_op.f("fk_games_remixed_from_game_id_games"),
            "games",
            ["remixed_from_game_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("games") as batch_op:
        batch_op.drop_constraint(batch_op.f("fk_games_remixed_from_game_id_games"), type_="foreignkey")
        batch_op.drop_index(batch_op.f("ix_games_remixed_from_game_id"))
        batch_op.drop_column("remixed_from_version")
        batch_op.drop_column("remixed_from_game_id")
