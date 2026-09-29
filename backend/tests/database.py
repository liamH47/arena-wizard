"""One place that decides which database a test runs on.

Without `AW_TEST_DB_URL` every test gets its own migrated SQLite file. With it (CI points it
at a real Postgres), every test gets that database with a clean, freshly migrated schema, so
the whole repository and API suite runs on the production dialect (decision 0008). The
schema is dropped and migrated again, never built with `create_all`, so the tests always
exercise the migrations.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import Engine, text

from arena_wizard.db.models import Base
from arena_wizard.db.session import make_engine
from arena_wizard.entrypoint import migrate

ENV = "AW_TEST_DB_URL"
ENGINES: list[Engine] = []
"""Engines opened by the app factories, disposed after each test so a shared Postgres never
runs out of connections."""


def _quiet(_: str) -> None:
    """Swallow the entrypoint's migration log lines."""


def reset_schema(url: str) -> None:
    """Drop every table the models know, and Alembic's own, leaving an empty database."""
    engine = make_engine(url)
    try:
        with engine.begin() as connection:
            Base.metadata.drop_all(connection)
            connection.execute(text("DROP TABLE IF EXISTS alembic_version"))
    finally:
        engine.dispose()


def fresh_database(tmp_path: Path, name: str = "app.db") -> str:
    """A migrated database URL: the shared one reset, or a new SQLite file."""
    shared = os.environ.get(ENV)
    if shared:
        reset_schema(shared)
        url = shared
    else:
        url = f"sqlite:///{(tmp_path / name).as_posix()}"
    migrate(url, _quiet)
    return url


def tracked_engine(url: str) -> Engine:
    """An engine the per-test cleanup will dispose."""
    engine = make_engine(url)
    ENGINES.append(engine)
    return engine


def dispose_all() -> None:
    """Dispose every tracked engine."""
    while ENGINES:
        ENGINES.pop().dispose()
