"""Shared by downgrades: refuse to destroy rows unless explicitly allowed (docs/schema.md)."""

from __future__ import annotations

import os

import sqlalchemy as sa
from alembic import context, op

ALLOW = "ARENA_WIZARD_ALLOW_DESTRUCTIVE_DOWNGRADE"


def refuse_destructive(tables: tuple[str, ...]) -> None:
    """Raise if dropping these tables would delete rows and the override is not set."""
    if context.is_offline_mode():
        raise RuntimeError("this downgrade counts rows first, so it cannot run as offline SQL")
    bind = op.get_bind()
    counts: dict[str, int] = {
        t: bind.execute(sa.text(f"SELECT COUNT(*) FROM {t}")).scalar_one() for t in tables
    }
    rows = {t: n for t, n in counts.items() if n}
    if rows and os.environ.get(ALLOW) != "1":
        raise RuntimeError(f"downgrade would delete rows {rows}; set {ALLOW}=1 to allow it")
