"""The group's card adjustments and their append-only log (decision 0011).

Additive only, so a build that predates it still boots against it (decision 0008).

Revision ID: 0002
Revises: 0001
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from arena_wizard.db.migrations.guard import refuse_destructive

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply this migration."""
    op.create_table(
        "card_adjustment_log",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("set_code", sa.String(length=8), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("action", sa.String(length=8), nullable=False),
        sa.Column("bomb", sa.String(length=8), nullable=True),
        sa.Column("q_delta", sa.Float(), nullable=True),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("changed_by", sa.String(length=255), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["changed_by"],
            ["users.user_id"],
            name=op.f("fk_card_adjustment_log_changed_by_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_card_adjustment_log")),
    )
    op.create_table(
        "card_adjustments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("set_code", sa.String(length=8), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("bomb", sa.String(length=8), nullable=True),
        sa.Column("q_delta", sa.Float(), nullable=True),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("updated_by", sa.String(length=255), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["users.user_id"],
            name=op.f("fk_card_adjustments_updated_by_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_card_adjustments")),
        sa.UniqueConstraint("set_code", "name", name=op.f("uq_card_adjustments_set_code")),
    )


def downgrade() -> None:
    """Undo this migration, refusing to destroy rows unless explicitly allowed."""
    refuse_destructive(("card_adjustments", "card_adjustment_log"))
    op.drop_table("card_adjustments")
    op.drop_table("card_adjustment_log")
