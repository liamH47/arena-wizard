"""Alembic's environment: the URL comes from Settings, the schema from the models."""

from __future__ import annotations

from alembic import context
from sqlalchemy import Connection, text

from arena_wizard.config import Settings
from arena_wizard.db.models import Base
from arena_wizard.db.session import make_engine, migration_lock_sql

config = context.config
TARGET = Base.metadata


def _url() -> str:
    """An explicit URL (tests, the entrypoint) wins over Settings."""
    explicit = config.get_main_option("sqlalchemy.url")
    return explicit if explicit else Settings().database_url


def _run(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=TARGET,
        render_as_batch=connection.dialect.name == "sqlite",
        compare_type=True,
    )
    with context.begin_transaction():
        connection.execute(text(migration_lock_sql(connection.dialect.name)))
        context.run_migrations()


if context.is_offline_mode():
    context.configure(url=_url(), target_metadata=TARGET, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = make_engine(_url())
    try:
        with engine.connect() as connection:
            _run(connection)
    finally:
        engine.dispose()
