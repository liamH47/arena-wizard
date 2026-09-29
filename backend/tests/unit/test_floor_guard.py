from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from arena_wizard.datadir import PRIVATE_MARKER
from arena_wizard.devtools.floor_guard import (
    CI_GATE_COMMAND,
    CI_GATE_COMMANDS,
    EVAL_GATE_COMMAND,
    CoverageRules,
    GuardError,
    check,
    collect_rules,
    count_pragmas,
    database_file_failures,
    evaluate,
    parse_floor,
    private_data_failures,
    rules_from_texts,
    run_git,
)

# Built in pieces so this test file does not count as containing pragmas itself.
PRAGMA = "# prag" + "ma: no cover"
ODD_SPELLING = "#PRAG" + "MA nocover"
BRANCH_PRAGMA = "# prag" + "ma: no branch"

PYPROJECT = """
[tool.coverage.run]
branch = true
source = ["src/pkg"]
omit = ["src/generated/*"]

[tool.coverage.report]
exclude_also = ['def main\\(']
"""


def _rules(**overrides: object) -> CoverageRules:
    values: dict[str, object] = {
        "floor": 100,
        "pragma_count": 0,
        "exclusions": ("def main\\(",),
        "partial_branches": (),
        "omissions": (),
        "scope": ("src/pkg",),
    }
    values.update(overrides)
    return CoverageRules(**values)  # type: ignore[arg-type]


def _done(returncode: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(["git"], returncode, stdout, stderr)


# --- pure pieces ---------------------------------------------------------------------------


def test_the_floor_file_parses_with_surrounding_whitespace() -> None:
    assert parse_floor(" 99\n") == 99


@pytest.mark.parametrize("text", ["101", "-1", "ninety"])
def test_a_floor_outside_zero_to_one_hundred_is_rejected(text: str) -> None:
    with pytest.raises(ValueError):
        parse_floor(text)


def test_git_grep_counts_are_summed_with_or_without_a_ref_prefix() -> None:
    output = "backend/src/a.py:2\norigin/main:backend/tests/b.py:1\n\n"
    assert count_pragmas(_done(0, output)) == 3


def test_git_grep_finding_nothing_is_zero_pragmas() -> None:
    assert count_pragmas(_done(1)) == 0


def test_a_failed_git_grep_fails_closed_instead_of_counting_zero() -> None:
    with pytest.raises(GuardError, match="bad revision"):
        count_pragmas(_done(128, stderr="fatal: bad revision"))


def test_rules_read_every_coverage_setting_that_changes_what_is_measured() -> None:
    text = PYPROJECT + "exclude_lines = ['raise']\npartial_branches = ['while True']\n"
    rules = rules_from_texts("100\n", text, pragma_count=2)
    assert rules == CoverageRules(
        floor=100,
        pragma_count=2,
        exclusions=("def main\\(", "raise"),
        partial_branches=("while True",),
        omissions=("src/generated/*",),
        scope=("src/pkg",),
    )


def test_a_pyproject_without_coverage_settings_has_no_exclusions() -> None:
    assert rules_from_texts("100", "[project]\nname = 'x'\n", 0).exclusions == ()


def test_a_base_without_a_floor_file_is_the_bootstrap_and_passes() -> None:
    assert evaluate(None, _rules(floor=0)) == ()


def test_an_unchanged_ratchet_passes_and_a_raised_floor_passes() -> None:
    assert evaluate(_rules(floor=99), _rules(floor=100)) == ()


@pytest.mark.parametrize(
    ("head", "message"),
    [
        (_rules(floor=98), "lowered from 100 to 98"),
        (_rules(pragma_count=1), "pragmas grew from 0 to 1"),
        (_rules(exclusions=("def main\\(", "raise NotImplementedError")), "exclusions gained"),
        (_rules(partial_branches=("while True",)), "partial branches gained"),
        (_rules(omissions=("src/pkg/cli.py",)), "omit gained"),
        (_rules(scope=("src/pkg/engine",)), "scope changed"),
    ],
)
def test_each_way_of_testing_less_is_reported(head: CoverageRules, message: str) -> None:
    failures = evaluate(_rules(), head)
    assert len(failures) == 1
    assert message in failures[0]


# --- against real git repositories -------------------------------------------------------


def _git(root: Path, *args: str) -> None:
    result = run_git(root, "-c", "user.name=test", "-c", "user.email=test@example.com", *args)
    assert result.returncode == 0, result.stderr


def _write(root: Path, path: str, text: str) -> None:
    file = root / path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(text, encoding="utf-8", newline="\n")


CI_TEXT = "steps:\n" + "".join(f"  - run: {command} origin/main\n" for command in CI_GATE_COMMANDS)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repository whose `base` branch has a floor of 100, one pragma, and an intact CI."""
    _git(tmp_path, "init", "-q")
    _write(tmp_path, "backend/coverage_floor.txt", "100\n")
    _write(tmp_path, "backend/pyproject.toml", PYPROJECT)
    _write(tmp_path, "backend/src/pkg/a.py", f"x = 1  {PRAGMA}\ny = 2\n")
    _write(tmp_path, ".github/workflows/ci.yml", CI_TEXT)
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "base")
    _git(tmp_path, "branch", "base")
    return tmp_path


def test_run_git_runs_in_the_given_directory_and_never_raises(tmp_path: Path) -> None:
    assert run_git(tmp_path, "init", "-q").returncode == 0
    assert run_git(tmp_path, "rev-parse", "--is-inside-work-tree").stdout.strip() == "true"
    assert run_git(tmp_path, "show", "HEAD:missing.txt").returncode != 0


def test_an_untouched_working_tree_holds_the_ratchet(repo: Path) -> None:
    assert check(repo, "base") == ()


def test_rules_are_read_from_a_ref_as_well_as_the_working_tree(repo: Path) -> None:
    _write(repo, "backend/coverage_floor.txt", "99\n")
    assert collect_rules(repo, "base") == _rules(pragma_count=1, omissions=("src/generated/*",))
    head = collect_rules(repo, None)
    assert head is not None and head.floor == 99


def test_lowering_the_floor_against_the_base_fails(repo: Path) -> None:
    _write(repo, "backend/coverage_floor.txt", "99\n")
    assert check(repo, "base") == ("coverage floor lowered from 100 to 99",)


@pytest.mark.parametrize("spelling", [PRAGMA, ODD_SPELLING, BRANCH_PRAGMA])
def test_a_new_pragma_in_any_spelling_fails_even_before_it_is_committed(
    repo: Path, spelling: str
) -> None:
    _write(repo, "backend/tests/test_new.py", f"def f():  {spelling}\n    pass\n")
    assert check(repo, "base") == ("coverage-exclusion pragmas grew from 1 to 2",)


def test_moving_coverage_settings_into_a_coveragerc_fails(repo: Path) -> None:
    _write(repo, "backend/.coveragerc", "[report]\nfail_under = 0\n")
    assert check(repo, "base") == (
        "backend/.coveragerc exists; coverage settings belong in backend/pyproject.toml",
    )


def test_editing_the_ci_gate_command_fails(repo: Path) -> None:
    edited = CI_TEXT.replace(CI_GATE_COMMAND, "uv run pytest --cov-fail-under=0")
    _write(repo, ".github/workflows/ci.yml", edited)
    assert check(repo, "base") == (f".github/workflows/ci.yml no longer runs `{CI_GATE_COMMAND}`",)


def test_dropping_the_evaluation_gate_from_ci_fails(repo: Path) -> None:
    _write(repo, ".github/workflows/ci.yml", f"steps:\n  - run: {CI_GATE_COMMAND}\n")
    assert check(repo, "base") == (
        f".github/workflows/ci.yml no longer runs `{EVAL_GATE_COMMAND}`",
    )


def test_a_missing_ci_workflow_fails_for_both_gates(repo: Path) -> None:
    (repo / ".github" / "workflows" / "ci.yml").unlink()
    failures = check(repo, "base")
    assert len(failures) == 2 and all("no longer runs" in f for f in failures)


def test_a_base_that_predates_the_floor_file_is_the_bootstrap(repo: Path) -> None:
    _git(repo, "checkout", "-q", "--orphan", "empty")
    _git(repo, "rm", "-q", "-r", "--cached", ".")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "empty")
    assert collect_rules(repo, "empty") is None
    assert check(repo, "empty") == ()


def test_an_unreadable_base_ref_fails(repo: Path) -> None:
    assert check(repo, "origin/nope") == (
        "cannot read origin/nope; fetch it before running the floor guard",
    )


def test_a_working_tree_without_a_floor_file_fails(repo: Path) -> None:
    (repo / "backend" / "coverage_floor.txt").unlink()
    assert check(repo, "base") == ("backend/coverage_floor.txt is missing",)


def test_a_file_carrying_the_private_marker_fails_whether_committed_or_not(repo: Path) -> None:
    _write(repo, "backend/eval/leak.json", f'{{"kind": "{PRIVATE_MARKER}"}}\n')
    assert check(repo, "base") == (
        "private pasted data is in the repository: backend/eval/leak.json",
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "leak")
    _write(repo, "notes.txt", PRIVATE_MARKER)
    assert private_data_failures(repo) == (
        "private pasted data is in the repository: backend/eval/leak.json, notes.txt",
    )


def test_an_ignored_file_with_the_marker_is_not_in_the_repository(repo: Path) -> None:
    _write(repo, ".gitignore", "scratch/\n")
    _write(repo, "scratch/paste.json", PRIVATE_MARKER)
    assert private_data_failures(repo) == ()


def test_a_failing_grep_for_private_data_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(GuardError, match="broken"):
        private_data_failures(tmp_path, lambda root, *args: _done(2, stderr="broken"))


def test_this_repository_carries_no_private_data() -> None:
    root = Path(run_git(Path.cwd(), "rev-parse", "--show-toplevel").stdout.strip())
    assert private_data_failures(root) == ()


def test_a_database_file_git_would_commit_fails(repo: Path) -> None:
    _write(repo, "backend/web.db", "rows")
    assert check(repo, "base") == ("database files would be committed: backend/web.db",)


def test_an_ignored_database_file_is_fine(repo: Path) -> None:
    _write(repo, ".gitignore", "*.sqlite3\n")
    _write(repo, "local.sqlite3", "rows")
    assert database_file_failures(repo) == ()


def test_a_git_failure_listing_database_files_fails_closed(tmp_path: Path) -> None:
    def broken(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(["git", *args], 128, "", "not a repository")

    with pytest.raises(GuardError, match="ls-files failed"):
        database_file_failures(tmp_path, broken)
