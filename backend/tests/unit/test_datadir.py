"""The private data directory and the UTC day (decision 0007)."""

from __future__ import annotations

import datetime as dt
import os
import socket
from pathlib import Path

import pytest

from arena_wizard.datadir import (
    DATA_DIR_ENV,
    PRIVATE_MARKER,
    DataDirError,
    git_work_tree,
    resolve_data_dir,
    utc_day,
)

PACIFIC = dt.timezone(dt.timedelta(hours=-7))


def test_an_evening_on_the_west_coast_is_already_the_next_utc_day() -> None:
    assert utc_day(dt.datetime(2026, 10, 9, 23, 30, tzinfo=PACIFIC)) == dt.date(2026, 10, 10)
    assert utc_day(dt.datetime(2026, 10, 9, 16, 59, tzinfo=PACIFIC)) == dt.date(2026, 10, 9)


def test_a_naive_timestamp_is_refused_because_its_utc_day_is_unknown() -> None:
    with pytest.raises(ValueError, match="naive"):
        utc_day(dt.datetime(2026, 10, 9, 23, 30))


def test_the_default_directory_is_under_the_home_directory(tmp_path: Path) -> None:
    assert resolve_data_dir(None, tmp_path) == (tmp_path / ".local/share/arena-wizard").resolve()
    assert resolve_data_dir("", tmp_path) == (tmp_path / ".local/share/arena-wizard").resolve()


def test_an_explicit_directory_outside_any_repository_is_used(tmp_path: Path) -> None:
    assert (
        resolve_data_dir(str(tmp_path / "private"), Path("/unused"))
        == (tmp_path / "private").resolve()
    )


def test_a_directory_inside_a_git_work_tree_is_refused(tmp_path: Path) -> None:
    (tmp_path / "repo" / ".git").mkdir(parents=True)
    inside = tmp_path / "repo" / "backend" / "eval"
    with pytest.raises(DataDirError, match="inside the git work tree"):
        resolve_data_dir(str(inside), tmp_path)
    assert git_work_tree(inside) == tmp_path / "repo"
    assert git_work_tree(tmp_path) is None


def test_this_repository_cannot_hold_private_data() -> None:
    with pytest.raises(DataDirError):
        resolve_data_dir(str(Path(__file__).parent), Path.home())


def test_the_marker_is_not_spelled_out_in_the_source_that_defines_it() -> None:
    source = (Path(__file__).parents[2] / "src/arena_wizard/datadir.py").read_text("utf-8")
    assert PRIVATE_MARKER not in source


def test_tests_run_against_a_temporary_data_directory_and_no_network() -> None:
    data = Path(os.environ[DATA_DIR_ENV])
    assert git_work_tree(data) is None and "home" not in data.name
    with pytest.raises(OSError, match="network"):
        socket.create_connection(("93.184.216.34", 443), timeout=1)
