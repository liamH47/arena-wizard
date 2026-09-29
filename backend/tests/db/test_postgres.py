"""What only a real Postgres can prove. Skipped locally without AW_TEST_PG_URL; CI sets
AW_TEST_PG_REQUIRED=1 so a missing database fails instead of silently skipping.

The rest of the repository and API suite also runs on CI's Postgres through
`AW_TEST_DB_URL` (tests/database.py); these tests cover what that suite cannot: the
migration lock, the engine's options against the real driver, the server's time zone,
constraint names, and values only Postgres refuses.
"""

from __future__ import annotations

import datetime as dt
import os
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from arena_wizard.db import repository
from arena_wizard.db.models import BuildRow, PasteRow, User
from arena_wizard.db.session import make_engine, migration_lock_sql, session_factory
from arena_wizard.entrypoint import alembic_config, database_revision, migrate
from tests.api.app_fixture import ALICE, as_user, make
from tests.database import dispose_all, reset_schema
from tests.db.test_repository import _card_paste

pytestmark = pytest.mark.postgres

NOW = dt.datetime(2026, 10, 3, 12, 0, tzinfo=dt.UTC)
PACIFIC = dt.timezone(dt.timedelta(hours=-7))
ALLOW = "ARENA_WIZARD_ALLOW_DESTRUCTIVE_DOWNGRADE"


def _quiet(_: str) -> None:
    """Swallow migration log lines."""


@pytest.fixture
def pg_url(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    url = os.environ.get("AW_TEST_PG_URL")
    if not url:
        if os.environ.get("AW_TEST_PG_REQUIRED") == "1":
            pytest.fail("AW_TEST_PG_REQUIRED=1 but AW_TEST_PG_URL is not set")
        pytest.skip("no Postgres: set AW_TEST_PG_URL to run")
    reset_schema(url)
    migrate(url, _quiet)
    monkeypatch.setenv(ALLOW, "1")
    yield url
    dispose_all()
    reset_schema(url)


@pytest.fixture
def pg(pg_url: str) -> Iterator[Session]:
    engine = make_engine(pg_url)
    with session_factory(engine)() as session:
        repository.upsert_user(session, "alice", "a@example.com", "", "", NOW)
        yield session
    engine.dispose()


def _tables(url: str) -> set[str]:
    engine = make_engine(url)
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_upgrade_creates_every_table_and_downgrade_removes_them(pg_url: str) -> None:
    assert {"users", "pools", "builds", "decks", "deck_runs", "pastes", "paste_deletions"} <= (
        _tables(pg_url)
    )
    command.downgrade(alembic_config(pg_url), "base")
    assert _tables(pg_url) == {"alembic_version"}
    assert database_revision(pg_url) is None
    command.upgrade(alembic_config(pg_url), "head")
    assert database_revision(pg_url) == "0001"


def test_a_second_migrator_waits_for_the_first_to_commit(pg_url: str) -> None:
    reset_schema(pg_url)
    holder_engine = make_engine(pg_url)
    holder = holder_engine.connect()
    holder.begin()
    holder.execute(text(migration_lock_sql("postgresql")))
    worker = threading.Thread(target=migrate, args=(pg_url, _quiet))
    worker.start()
    worker.join(timeout=2)
    try:
        assert worker.is_alive(), "the migration did not wait for the advisory lock"
        assert database_revision(pg_url) is None
    finally:
        # Transaction-scoped: ending the transaction releases the lock.
        holder.rollback()
        holder.close()
        holder_engine.dispose()
    worker.join(timeout=30)
    assert not worker.is_alive()
    assert database_revision(pg_url) == "0001"


def _connections(url: str) -> int:
    engine = make_engine(url)
    try:
        with engine.connect() as connection:
            count: int = connection.execute(
                text("SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()")
            ).scalar_one()
            return count
    finally:
        engine.dispose()


def test_migrating_leaves_no_connection_open(pg_url: str) -> None:
    before = _connections(pg_url)
    migrate(pg_url, _quiet)
    deadline = time.monotonic() + 5
    while _connections(pg_url) != before and time.monotonic() < deadline:
        time.sleep(0.1)
    assert _connections(pg_url) == before


def test_a_failed_insert_never_carries_the_pasted_rows(pg: Session) -> None:
    with pytest.raises(IntegrityError) as raised:
        repository.save_paste(pg, _card_paste(), "nobody", NOW, None)
    message = str(raised.value)
    assert "Made-up Knight" not in message
    assert "hidden due to hide_parameters" in message


def test_the_driver_never_prepares_statements(pg_url: str) -> None:
    engine = make_engine(pg_url)
    try:
        with engine.connect() as connection:
            driver = connection.connection.dbapi_connection
            assert driver is not None and driver.prepare_threshold is None
    finally:
        engine.dispose()


def test_a_duplicate_paste_key_is_refused_by_the_named_constraint(pg: Session) -> None:
    def row() -> PasteRow:
        return PasteRow(
            set_code="FRA",
            dataset="grades",
            event_type="grades",
            source_id="llu-marc",
            import_day=dt.date(2026, 10, 3),
            label="x",
            url=None,
            copied_on=dt.date(2026, 10, 3),
            published_on=None,
            columns=[],
            rows=[],
            text_sha256="a" * 64,
            parser_version=1,
            pasted_by="alice",
            pasted_at=NOW,
            replaced_at=None,
        )

    pg.add(row())
    pg.commit()
    pg.add(row())
    with pytest.raises(IntegrityError, match="uq_pastes_set_code"):
        pg.commit()
    pg.rollback()


def test_a_duplicate_build_key_is_refused_by_the_named_constraint(pg: Session) -> None:
    pool = "11111111-1111-1111-1111-111111111111"
    repository.create_pool(pg, "alice", pool, "FRA", "bo1_sealed", "x", "h", "p", NOW)
    for _ in range(2):
        pg.add(
            BuildRow(
                pool_id=pool,
                inputs_key="k",
                config_version="0.3",
                mode="event",
                data_lines=[],
                refusal=None,
                created_at=NOW,
            )
        )
    with pytest.raises(IntegrityError, match="uq_builds_pool_id"):
        pg.commit()
    pg.rollback()


def test_a_pool_with_a_recorded_run_cannot_be_deleted(pg: Session) -> None:
    pool = "11111111-1111-1111-1111-111111111111"
    repository.create_pool(pg, "alice", pool, "FRA", "bo1_sealed", "x", "h", "p", NOW)
    build = repository.save_build(
        pg,
        pool,
        "k",
        "0.3",
        "event",
        [],
        None,
        [repository.NewDeck("WU", None, 1.0, 1.0, {})],
        NOW,
    )
    repository.create_run(pg, "alice", "r", build.id, 0, 1, 1, "", "", "h", NOW)
    with pytest.raises(repository.InUse):
        repository.delete_pool(pg, "alice", pool)
    repository.delete_run(pg, "alice", "r")


def test_timestamps_come_back_in_utc_whatever_the_session_time_zone(pg: Session) -> None:
    evening = dt.datetime(2026, 10, 9, 23, 30, tzinfo=PACIFIC)
    repository.upsert_user(pg, "alice", "a@example.com", "", "", evening)
    pg.execute(text("SET TIME ZONE 'America/Los_Angeles'"))
    pg.expire_all()
    user = pg.get(User, "alice")
    assert user is not None and user.last_seen_at == evening
    assert user.last_seen_at.tzinfo is dt.UTC
    assert user.last_seen_at.isoformat().endswith("+00:00")


def test_a_nul_that_reaches_postgres_is_a_422_not_a_500(pg_url: str, tmp_path: Path) -> None:
    _, client, _ = make(tmp_path, url=pg_url)
    pastes = client.get("/api/pastes", params={"set_code": "FR\x00"}, headers=as_user(ALICE))
    assert pastes.status_code == 422
    assert pastes.json() == {"detail": "a value in the request cannot be stored"}
    pool = client.get("/api/pools/%00", headers=as_user(ALICE))
    assert pool.status_code == 422
