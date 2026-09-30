from __future__ import annotations

import datetime as dt
import io
from contextlib import redirect_stdout
from importlib import resources
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from arena_wizard.db import repository
from arena_wizard.db.models import Base
from arena_wizard.db.session import make_engine
from arena_wizard.entrypoint import alembic_config

ALLOW = "ARENA_WIZARD_ALLOW_DESTRUCTIVE_DOWNGRADE"
TABLES = {
    "users",
    "pools",
    "builds",
    "decks",
    "deck_runs",
    "pastes",
    "paste_deletions",
    "card_adjustments",
    "card_adjustment_log",
    "alembic_version",
}


def _tables(url: str) -> set[str]:
    engine = make_engine(url)
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_the_migrated_schema_matches_the_models_exactly(db_url: str) -> None:
    engine = make_engine(db_url)
    with engine.connect() as connection:
        diff = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    engine.dispose()
    assert diff == []
    assert _tables(db_url) == TABLES


def test_upgrading_twice_is_a_no_op(db_url: str) -> None:
    command.upgrade(alembic_config(db_url), "head")
    assert _tables(db_url) == TABLES


def test_an_empty_database_downgrades_to_nothing_and_back(db_url: str) -> None:
    command.downgrade(alembic_config(db_url), "base")
    assert _tables(db_url) == {"alembic_version"}
    command.upgrade(alembic_config(db_url), "head")
    assert _tables(db_url) == TABLES


def test_a_downgrade_that_would_delete_rows_is_refused_unless_allowed(
    db_url: str, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    session.close()
    monkeypatch.delenv(ALLOW, raising=False)
    command.downgrade(alembic_config(db_url), "0001")  # no adjustments, so allowed
    with pytest.raises(RuntimeError, match=r"would delete rows \{'users': 2\}"):
        command.downgrade(alembic_config(db_url), "base")
    assert _tables(db_url) == TABLES - {"card_adjustments", "card_adjustment_log"}
    monkeypatch.setenv(ALLOW, "1")
    command.downgrade(alembic_config(db_url), "base")
    assert _tables(db_url) == {"alembic_version"}


def test_downgrading_0002_refuses_to_drop_adjustments_unless_allowed(
    db_url: str, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = dt.datetime(2026, 10, 1, tzinfo=dt.UTC)
    repository.set_adjustment(session, "HOB", "A Card", "add", None, "", "alice", now)
    session.close()
    monkeypatch.delenv(ALLOW, raising=False)
    with pytest.raises(RuntimeError, match=r"'card_adjustments': 1, 'card_adjustment_log': 1"):
        command.downgrade(alembic_config(db_url), "0001")
    monkeypatch.setenv(ALLOW, "1")
    command.downgrade(alembic_config(db_url), "0001")
    assert _tables(db_url) == TABLES - {"card_adjustments", "card_adjustment_log"}


def test_offline_mode_writes_the_sql_without_a_database(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path.as_posix()}/never.db"
    out = io.StringIO()
    with redirect_stdout(out):
        command.upgrade(alembic_config(url), "head", sql=True)
    sql = out.getvalue()
    assert sql.count("CREATE TABLE") == len(TABLES)
    assert not (tmp_path / "never.db").exists()


def test_without_an_explicit_url_the_settings_url_is_migrated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = f"sqlite:///{tmp_path.as_posix()}/from_env.db"
    monkeypatch.setenv("ARENA_WIZARD_DATABASE_URL", url)
    config = Config()
    config.set_main_option(
        "script_location", str(resources.files("arena_wizard").joinpath("db", "migrations"))
    )
    command.upgrade(config, "head")
    assert _tables(url) == TABLES


def test_the_revision_is_recorded(db_url: str) -> None:
    engine = make_engine(db_url)
    with engine.connect() as connection:
        assert (
            connection.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0002"
        )
    engine.dispose()


def test_the_downgrade_refuses_to_run_as_offline_sql(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path.as_posix()}/never.db"
    with (
        redirect_stdout(io.StringIO()),
        pytest.raises(RuntimeError, match="cannot run as offline SQL"),
    ):
        command.downgrade(alembic_config(url), "0001:base", sql=True)
