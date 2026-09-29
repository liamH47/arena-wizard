from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from arena_wizard.devtools.floor_guard import run_git
from arena_wizard.eval.base import REPORT_PATH, BaseUnavailable, read_base_report


def _git(root: Path, *args: str) -> None:
    result = run_git(root, "-c", "user.name=test", "-c", "user.email=test@example.com", *args)
    assert result.returncode == 0, result.stderr


def _commit(root: Path, message: str) -> None:
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", message)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q")
    (tmp_path / "README").write_text("x\n", encoding="utf-8", newline="\n")
    _commit(tmp_path, "before the report")
    _git(tmp_path, "branch", "old")
    report = tmp_path / REPORT_PATH
    report.parent.mkdir(parents=True)
    report.write_text(json.dumps({"decision_digest": "abc"}), encoding="utf-8", newline="\n")
    _commit(tmp_path, "add the report")
    _git(tmp_path, "branch", "base")
    return tmp_path


def test_the_base_ref_s_committed_report_is_read_not_the_working_tree(repo: Path) -> None:
    (repo / REPORT_PATH).write_text("{}", encoding="utf-8", newline="\n")
    assert read_base_report(repo, "base") == {"decision_digest": "abc"}


def test_a_base_that_predates_the_report_is_the_bootstrap_case(repo: Path) -> None:
    assert read_base_report(repo, "old") is None


def test_an_unreadable_base_ref_fails_closed(repo: Path) -> None:
    with pytest.raises(BaseUnavailable, match="origin/main"):
        read_base_report(repo, "origin/main")


def test_the_git_runner_is_injectable(tmp_path: Path) -> None:
    calls: list[tuple[str, ...]] = []

    def git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        out = '{"sets": {}}' if args[0] == "show" else ""
        return subprocess.CompletedProcess(["git", *args], 0, out, "")

    assert read_base_report(tmp_path, "main", git=git) == {"sets": {}}
    assert calls == [
        ("rev-parse", "--verify", "main^{commit}"),
        ("show", f"main:{REPORT_PATH}"),
    ]
