from __future__ import annotations

from pathlib import Path

import pytest

from arena_wizard.devtools.floor_guard import (
    PRAGMA_MARKER,
    CoverageRules,
    count_pragmas,
    evaluate,
    parse_floor,
    rules_from_texts,
    run_git,
)

PYPROJECT = """
[tool.coverage.run]
branch = true
omit = ["src/generated/*"]

[tool.coverage.report]
exclude_also = ['def main\\(']
"""


def _rules(**overrides: object) -> CoverageRules:
    values: dict[str, object] = {
        "floor": 100,
        "pragma_count": 0,
        "exclusions": ("def main\\(",),
        "omissions": (),
    }
    values.update(overrides)
    return CoverageRules(**values)  # type: ignore[arg-type]


def test_the_floor_file_parses_with_surrounding_whitespace() -> None:
    assert parse_floor(" 99\n") == 99


@pytest.mark.parametrize("text", ["101", "-1", "ninety"])
def test_a_floor_outside_zero_to_one_hundred_is_rejected(text: str) -> None:
    with pytest.raises(ValueError):
        parse_floor(text)


def test_git_grep_counts_are_summed_with_or_without_a_ref_prefix() -> None:
    output = "backend/src/a.py:2\norigin/main:backend/tests/b.py:1\n\n"
    assert count_pragmas(output) == 3


def test_rules_read_exclusions_and_omissions_from_pyproject() -> None:
    rules = rules_from_texts("100\n", PYPROJECT, pragma_count=2)
    assert rules == CoverageRules(100, 2, ("def main\\(",), ("src/generated/*",))


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
        (_rules(pragma_count=1), f"'{PRAGMA_MARKER}' pragmas grew from 0 to 1"),
        (_rules(exclusions=("def main\\(", "raise NotImplementedError")), "exclude_also"),
        (_rules(omissions=("src/arena_wizard/cli.py",)), "omit gained"),
    ],
)
def test_each_way_of_testing_less_is_reported(head: CoverageRules, message: str) -> None:
    failures = evaluate(_rules(), head)
    assert len(failures) == 1
    assert message in failures[0]


def test_run_git_runs_in_the_given_directory_and_never_raises(tmp_path: Path) -> None:
    assert run_git(tmp_path, "init", "-q").returncode == 0
    assert run_git(tmp_path, "rev-parse", "--is-inside-work-tree").stdout.strip() == "true"
    assert run_git(tmp_path, "show", "HEAD:missing.txt").returncode != 0
