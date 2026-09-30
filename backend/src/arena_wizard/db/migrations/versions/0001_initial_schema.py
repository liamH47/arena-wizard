"""The initial schema: users, pools, builds, decks, recorded runs, pastes, and deletions.

Why: milestone 3 moves the app onto a database (docs/plan.md section 5, decision 0008).
Pastes carry decision 0005's unique key with the event type (decision 0007); their rows are
one JSON column so a same-day replace is one row update. Paste deletions are logged without
their data. Timestamps are timezone-aware; the models make them UTC. `docs/schema.md`
describes every table.

Every later migration must leave the previous release working (add nullable or defaulted
columns; no drops or renames in the same release), so a rollback can still boot.

Revision ID: 0001
Revises:
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from arena_wizard.db.migrations.guard import refuse_destructive

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply this migration."""
    op.create_table(
        "users",
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("picture", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_users")),
    )
    op.create_table(
        "paste_deletions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("set_code", sa.String(length=8), nullable=False),
        sa.Column("dataset", sa.String(length=16), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("import_day", sa.Date(), nullable=False),
        sa.Column("pasted_by", sa.String(length=255), nullable=False),
        sa.Column("deleted_by", sa.String(length=255), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["deleted_by"],
            ["users.user_id"],
            name=op.f("fk_paste_deletions_deleted_by_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_paste_deletions")),
    )
    op.create_table(
        "pastes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("set_code", sa.String(length=8), nullable=False),
        sa.Column("dataset", sa.String(length=16), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("import_day", sa.Date(), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("copied_on", sa.Date(), nullable=False),
        sa.Column("published_on", sa.Date(), nullable=True),
        sa.Column("columns", sa.JSON(), nullable=False),
        sa.Column("rows", sa.JSON(), nullable=False),
        sa.Column("text_sha256", sa.String(length=64), nullable=False),
        sa.Column("parser_version", sa.Integer(), nullable=False),
        sa.Column("pasted_by", sa.String(length=255), nullable=False),
        sa.Column("pasted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("replaced_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["pasted_by"],
            ["users.user_id"],
            name=op.f("fk_pastes_pasted_by_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pastes")),
        sa.UniqueConstraint(
            "set_code",
            "dataset",
            "event_type",
            "source_id",
            "import_day",
            name=op.f("uq_pastes_set_code"),
        ),
    )
    op.create_table(
        "pools",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("set_code", sa.String(length=8), nullable=False),
        sa.Column("format", sa.String(length=32), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("body_hash", sa.String(length=64), nullable=False),
        sa.Column("pool_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.user_id"], name=op.f("fk_pools_user_id_users"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pools")),
    )
    with op.batch_alter_table("pools", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_pools_user_id"), ["user_id"], unique=False)

    op.create_table(
        "builds",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("pool_id", sa.String(length=36), nullable=False),
        sa.Column("inputs_key", sa.String(length=64), nullable=False),
        sa.Column("config_version", sa.String(length=32), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("data_lines", sa.JSON(), nullable=False),
        sa.Column("refusal", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["pool_id"], ["pools.id"], name=op.f("fk_builds_pool_id_pools"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_builds")),
        sa.UniqueConstraint("pool_id", "inputs_key", name=op.f("uq_builds_pool_id")),
    )
    op.create_table(
        "decks",
        sa.Column("build_id", sa.Integer(), nullable=False),
        sa.Column("deck_index", sa.Integer(), nullable=False),
        sa.Column("colors", sa.String(length=8), nullable=False),
        sa.Column("splash", sa.String(length=1), nullable=True),
        sa.Column("total", sa.Float(), nullable=False),
        sa.Column("total_se", sa.Float(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["build_id"], ["builds.id"], name=op.f("fk_decks_build_id_builds"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("build_id", "deck_index", name=op.f("pk_decks")),
    )
    op.create_table(
        "deck_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("build_id", sa.Integer(), nullable=False),
        sa.Column("deck_index", sa.Integer(), nullable=False),
        sa.Column("wins", sa.Integer(), nullable=False),
        sa.Column("losses", sa.Integer(), nullable=False),
        sa.Column("event_name", sa.String(length=255), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("extra", sa.JSON(), nullable=False),
        sa.Column("body_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["build_id", "deck_index"],
            ["decks.build_id", "decks.deck_index"],
            name=op.f("fk_deck_runs_build_id_decks"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.user_id"],
            name=op.f("fk_deck_runs_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_deck_runs")),
    )
    with op.batch_alter_table("deck_runs", schema=None) as batch_op:
        batch_op.create_index("ix_deck_runs_deck", ["build_id", "deck_index"], unique=False)
        batch_op.create_index(batch_op.f("ix_deck_runs_user_id"), ["user_id"], unique=False)


TABLES = ("paste_deletions", "deck_runs", "decks", "builds", "pools", "pastes", "users")


def downgrade() -> None:
    """Undo this migration, refusing to destroy rows unless explicitly allowed."""
    refuse_destructive(TABLES)
    with op.batch_alter_table("deck_runs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_deck_runs_user_id"))
        batch_op.drop_index("ix_deck_runs_deck")

    op.drop_table("deck_runs")
    op.drop_table("decks")
    op.drop_table("builds")
    with op.batch_alter_table("pools", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_pools_user_id"))

    op.drop_table("pools")
    op.drop_table("pastes")
    op.drop_table("paste_deletions")
    op.drop_table("users")
