"""Liveness and readiness, and the warming answer while the database wakes."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import DataError, IntegrityError, OperationalError

from arena_wizard import __version__
from arena_wizard.config import Settings
from arena_wizard.main import create_app
from tests.api.app_fixture import NOON as FIXED
from tests.api.app_fixture import Clock, make


class NoDatabase:
    """A session factory that fails the test if anything opens a session."""

    def __call__(self) -> Any:
        raise AssertionError("this endpoint must not open a database session")


class AsleepSession:
    """A session whose database is still waking, like Neon after idling."""

    def __enter__(self) -> AsleepSession:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, *args: object) -> None:
        raise OperationalError("SELECT 1", {}, Exception("compute is waking"))


def _settings() -> Settings:
    return Settings(_env_file=None)  # type: ignore[call-arg]


def test_healthz_answers_ok_without_any_dependency() -> None:
    client = TestClient(create_app(_settings(), sessions=NoDatabase(), now=Clock()))  # type: ignore[arg-type]
    response = client.get("/healthz")
    assert response.status_code == 200 and response.json() == {"status": "ok"}


def test_readyz_reports_boot_time_and_version_without_touching_the_database() -> None:
    client = TestClient(create_app(_settings(), sessions=NoDatabase(), now=Clock()))  # type: ignore[arg-type]
    assert client.get("/readyz").json() == {
        "status": "ok",
        "version": __version__,
        "boot_at": FIXED.isoformat(),
        "commit": None,
        "last_db_error": None,
    }


def test_a_deep_readiness_check_round_trips_the_database(tmp_path: Path) -> None:
    _, client, _ = make(tmp_path)
    body = client.get("/readyz", params={"deep": 1}).json()
    assert body["status"] == "ok" and body["database"] == "ok"


def test_a_waking_database_answers_503_warming_with_retry_after() -> None:
    app = create_app(_settings(), sessions=AsleepSession, now=Clock())  # type: ignore[arg-type]
    response = TestClient(app).get("/readyz", params={"deep": 1})
    assert response.status_code == 503
    assert response.json() == {"status": "warming"}
    assert response.headers["retry-after"] == "5"


class _Original(Exception):
    def __init__(self, message: str, sqlstate: str | None) -> None:
        super().__init__(message)
        self.sqlstate = sqlstate


def _failing_sessions(error: Exception) -> type:
    class Failing:
        def __enter__(self) -> Failing:
            return self

        def __exit__(self, *exc: object) -> None:
            return None

        def execute(self, *args: object) -> None:
            raise error

    return Failing


def test_warming_logs_one_line_without_parameters_and_readyz_shows_it(
    caplog: pytest.LogCaptureFixture,
) -> None:
    error = OperationalError(
        "INSERT INTO pastes",
        {"rows": "Made-up Knight 57.5%"},
        _Original("compute is waking\nmore", "08006"),
    )
    app = create_app(_settings(), sessions=_failing_sessions(error), now=Clock())  # type: ignore[arg-type]
    client = TestClient(app)
    with caplog.at_level(logging.WARNING, logger="arena_wizard"):
        assert client.get("/readyz", params={"deep": 1}).status_code == 503
    (record,) = [r for r in caplog.records if r.name == "arena_wizard"]
    assert record.getMessage() == "database unavailable: _Original sqlstate=08006 compute is waking"
    assert "Made-up Knight" not in record.getMessage()
    assert client.get("/readyz").json()["last_db_error"] == {
        "at": FIXED.isoformat(),
        "type": "_Original",
        "sqlstate": "08006",
        "message": "compute is waking",
    }


@pytest.mark.parametrize("sqlstate", ["28P01", "3D000", "53100"])
def test_a_database_that_retrying_cannot_fix_is_a_database_error(sqlstate: str) -> None:
    error = OperationalError("SELECT 1", {}, _Original("password authentication failed", sqlstate))
    app = create_app(_settings(), sessions=_failing_sessions(error), now=Clock())  # type: ignore[arg-type]
    response = TestClient(app).get("/readyz", params={"deep": 1})
    assert response.status_code == 500 and response.json() == {"status": "database_error"}


def test_a_write_that_still_conflicts_is_a_409_without_the_rows(
    caplog: pytest.LogCaptureFixture,
) -> None:
    error = IntegrityError(
        "INSERT INTO pastes", {"rows": "Made-up Knight"}, Exception("FOREIGN KEY")
    )
    app = create_app(_settings(), sessions=_failing_sessions(error), now=Clock())  # type: ignore[arg-type]
    response = TestClient(app).get("/readyz", params={"deep": 1})
    assert response.status_code == 409 and "Made-up Knight" not in response.text


def test_health_checks_answer_head_requests() -> None:
    client = TestClient(create_app(_settings(), sessions=NoDatabase(), now=Clock()))  # type: ignore[arg-type]
    assert client.head("/healthz").status_code == 200
    assert client.head("/readyz").status_code == 200


def test_a_value_the_database_refuses_is_a_422_without_the_value() -> None:
    error = DataError(
        "SELECT FROM pastes", {"set_code": "FR\x00 Made-up Knight"}, Exception("NUL byte")
    )
    app = create_app(_settings(), sessions=_failing_sessions(error), now=Clock())  # type: ignore[arg-type]
    response = TestClient(app).get("/readyz", params={"deep": 1})
    assert response.status_code == 422
    assert response.json() == {"detail": "a value in the request cannot be stored"}
    assert "Made-up Knight" not in response.text
