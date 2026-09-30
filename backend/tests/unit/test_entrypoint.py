"""The container entrypoint: waiting for the database, then migrating."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import OperationalError

from arena_wizard.db.session import make_engine
from arena_wizard.entrypoint import (
    DEADLINE_SECONDS,
    DatabaseUnavailable,
    alembic_config,
    database_revision,
    migrate,
    wait_for_database,
)


class FakeTime:
    """A clock that only moves when something sleeps."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def _failing(times: int) -> tuple[list[int], object]:
    attempts: list[int] = []

    def connect() -> None:
        attempts.append(1)
        if len(attempts) <= times:
            raise OperationalError("connect", {}, Exception("Neon is waking"))

    return attempts, connect


def test_a_database_that_answers_at_once_takes_one_attempt() -> None:
    clock, lines = FakeTime(), list[str]()
    attempts, connect = _failing(0)
    assert wait_for_database(connect, clock.sleep, clock.monotonic, lines.append) == 1  # type: ignore[arg-type]
    assert clock.sleeps == [] and lines == ["database ready after 1 attempt(s)"]


def test_retries_back_off_doubling_up_to_ten_seconds_with_a_line_per_attempt() -> None:
    clock, lines = FakeTime(), list[str]()
    attempts, connect = _failing(6)
    assert wait_for_database(connect, clock.sleep, clock.monotonic, lines.append) == 7  # type: ignore[arg-type]
    assert clock.sleeps == [1.0, 2.0, 4.0, 8.0, 10.0, 10.0]
    assert len(lines) == 7 and lines[0].startswith("database not ready (attempt 1, 0s)")
    assert "Neon is waking" in lines[0] and lines[-1] == "database ready after 7 attempt(s)"


def test_it_gives_up_at_the_deadline_with_the_last_error_attached() -> None:
    clock, lines = FakeTime(), list[str]()
    attempts, connect = _failing(1000)
    with pytest.raises(DatabaseUnavailable, match="no database after") as caught:
        wait_for_database(connect, clock.sleep, clock.monotonic, lines.append)  # type: ignore[arg-type]
    assert isinstance(caught.value.__cause__, OperationalError)
    assert clock.now <= DEADLINE_SECONDS
    assert len(lines) == len(attempts) and sum(clock.sleeps) == clock.now


def test_the_alembic_config_uses_the_migrations_inside_the_package() -> None:
    config = alembic_config("sqlite:///example.db")
    location = resources.files("arena_wizard").joinpath("db", "migrations")
    assert config.get_main_option("script_location") == str(location)
    assert config.get_main_option("sqlalchemy.url") == "sqlite:///example.db"


def test_migrating_creates_every_table_and_a_second_run_changes_nothing(tmp_path: Path) -> None:
    url = f"sqlite:///{(tmp_path / 'm.db').as_posix()}"
    migrate(url)
    tables = set(inspect(make_engine(url)).get_table_names())
    assert {"users", "pools", "builds", "decks", "deck_runs", "pastes"} <= tables
    migrate(url)
    assert set(inspect(make_engine(url)).get_table_names()) == tables


def test_a_rolled_back_build_serves_a_newer_database_without_migrating(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path.as_posix()}/ahead.db"
    migrate(url, lambda line: None)
    engine = make_engine(url)
    with engine.begin() as connection:
        connection.execute(text("UPDATE alembic_version SET version_num = '9999'"))
    engine.dispose()
    lines: list[str] = []
    migrate(url, lines.append)
    assert lines == [
        "database at revision 9999, ahead of this build's head 0002; serving without "
        "migrating (a rollback)"
    ]
    assert database_revision(url) == "9999"


def test_migrating_names_where_it_starts_and_ends(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path.as_posix()}/fresh.db"
    lines: list[str] = []
    migrate(url, lines.append)
    migrate(url, lines.append)
    assert lines == [
        "migrating from an empty database to 0002",
        "migrating from 0002 to 0002",
    ]


def test_a_percent_encoded_password_survives_the_alembic_config() -> None:
    url = "postgresql+psycopg://user:p%40ss@db.example.com/app"
    assert alembic_config(url).get_main_option("sqlalchemy.url") == url
