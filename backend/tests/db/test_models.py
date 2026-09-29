from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import event, text
from sqlalchemy.dialects import sqlite
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from arena_wizard.db.models import PoolRow, User, UTCDateTime
from arena_wizard.db.session import MIGRATION_LOCK, make_engine, migration_lock_sql
from tests.db.conftest import NOW

DIALECT = sqlite.dialect()
PACIFIC = dt.timezone(dt.timedelta(hours=-7))


def test_a_naive_timestamp_is_refused_before_it_reaches_the_database() -> None:
    with pytest.raises(ValueError, match="naive"):
        UTCDateTime().process_bind_param(dt.datetime(2026, 10, 3, 12), DIALECT)


def test_aware_timestamps_are_stored_and_returned_in_utc() -> None:
    column = UTCDateTime()
    evening = dt.datetime(2026, 10, 9, 23, 30, tzinfo=PACIFIC)
    stored = column.process_bind_param(evening, DIALECT)
    assert stored == evening and stored is not None and stored.tzinfo == dt.UTC
    returned = column.process_result_value(evening, DIALECT)
    assert returned is not None and returned.tzinfo == dt.UTC and returned.day == 10
    assert column.process_bind_param(None, DIALECT) is None
    assert column.process_result_value(None, DIALECT) is None


def test_sqlite_returns_naive_times_which_come_back_as_utc(session: Session) -> None:
    session.expire_all()
    user = session.get(User, "alice")
    assert user is not None and user.created_at == NOW and user.created_at.tzinfo == dt.UTC


def test_sqlite_enforces_foreign_keys(session: Session) -> None:
    if session.get_bind().dialect.name != "sqlite":
        pytest.skip("SQLite's foreign-key pragma; Postgres always enforces them")
    assert session.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
    session.add(
        PoolRow(
            id="p",
            user_id="nobody",
            set_code="FRA",
            format="bo1_sealed",
            raw_text="",
            body_hash="h",
            pool_hash="p",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()


class _NoServer(Exception):
    """Raised in place of opening a socket, once the connect arguments are seen."""


def test_a_postgres_engine_hides_parameters_and_never_prepares_statements() -> None:
    engine = make_engine("postgresql+psycopg://user:pw@localhost:1/none")
    seen: dict[str, Any] = {}

    def capture(dialect: Any, record: Any, cargs: Any, cparams: dict[str, Any]) -> None:
        seen.update(cparams)
        raise _NoServer

    event.listen(engine, "do_connect", capture)
    with pytest.raises(_NoServer):
        engine.connect()
    assert engine.dialect.name == "postgresql" and engine.hide_parameters is True
    assert engine.pool._pre_ping is True and engine.pool._recycle == 300
    assert seen["prepare_threshold"] is None and seen["connect_timeout"] == 10
    engine.dispose()


def test_the_migration_lock_statement_is_an_advisory_lock_only_on_postgres() -> None:
    """The lock itself is proven against a real Postgres in test_postgres.py."""
    assert migration_lock_sql("postgresql") == f"SELECT pg_advisory_xact_lock({MIGRATION_LOCK})"
    assert migration_lock_sql("sqlite") == "SELECT 1"


def test_a_sqlite_file_in_a_missing_directory_is_created_on_first_connect(tmp_path: Path) -> None:
    target = tmp_path / "fresh" / "nested" / "web.db"
    engine = make_engine(f"sqlite:///{target.as_posix()}")
    with engine.connect():
        pass
    engine.dispose()
    assert target.is_file()


def test_an_in_memory_sqlite_database_needs_no_directory() -> None:
    engine = make_engine("sqlite:///:memory:")
    with engine.connect():
        pass
    engine.dispose()
