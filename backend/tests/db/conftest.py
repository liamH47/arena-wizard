from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from arena_wizard.db import repository
from arena_wizard.db.session import make_engine, session_factory
from tests.database import fresh_database

NOW = dt.datetime(2026, 10, 3, 12, 0, tzinfo=dt.UTC)
LATER = NOW + dt.timedelta(hours=1)


@pytest.fixture
def db_url(tmp_path: Path) -> str:
    """A freshly migrated database: SQLite, or the shared Postgres under AW_TEST_DB_URL."""
    return fresh_database(tmp_path, "t.db")


@pytest.fixture
def sessions(db_url: str) -> Iterator[sessionmaker[Session]]:
    engine = make_engine(db_url)
    yield session_factory(engine)
    engine.dispose()


@pytest.fixture
def session(sessions: sessionmaker[Session]) -> Iterator[Session]:
    with sessions() as s:
        repository.upsert_user(s, "alice", "alice@example.com", "Alice", "", NOW)
        repository.upsert_user(s, "bob", "bob@example.com", "Bob", "", NOW)
        yield s
