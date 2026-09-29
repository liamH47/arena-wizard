"""CI guard that keeps the coverage gate a ratchet.

Fails a pull request that lowers `coverage_floor.txt`, adds coverage-exclusion pragmas,
or grows the `exclude_also` or `omit` lists relative to the base branch. Each of those is
a way to make the number look the same while testing less.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

PRAGMA_MARKER = "pragma" + ": no cover"
"""Spelled in two parts so this file does not count itself."""

FLOOR_PATH = "backend/coverage_floor.txt"
PYPROJECT_PATH = "backend/pyproject.toml"
SOURCE_PATHS = ("backend/src", "backend/tests")


@dataclass(frozen=True, slots=True)
class CoverageRules:
    """Everything that decides how much code the coverage gate actually measures."""

    floor: int
    pragma_count: int
    exclusions: tuple[str, ...]
    omissions: tuple[str, ...]


def parse_floor(text: str) -> int:
    """Parse a coverage floor file.

    Args:
        text: The file's contents.

    Returns:
        The floor as a whole percentage.

    Raises:
        ValueError: The text is not an integer from 0 to 100.
    """
    value = int(text.strip())
    if not 0 <= value <= 100:
        raise ValueError(f"coverage floor must be 0 to 100, got {value}")
    return value


def count_pragmas(grep_output: str) -> int:
    """Sum the counts from `git grep -c` output, whose lines end in `:count`. Pure."""
    return sum(int(line.rsplit(":", 1)[1]) for line in grep_output.splitlines() if line.strip())


def rules_from_texts(floor_text: str, pyproject_text: str, pragma_count: int) -> CoverageRules:
    """Build the rules from file contents. Pure.

    Args:
        floor_text: Contents of the floor file.
        pyproject_text: Contents of pyproject.toml.
        pragma_count: How many exclusion pragmas the sources contain.

    Returns:
        The rules.
    """
    coverage = tomllib.loads(pyproject_text).get("tool", {}).get("coverage", {})
    run = coverage.get("run", {})
    report = coverage.get("report", {})
    return CoverageRules(
        floor=parse_floor(floor_text),
        pragma_count=pragma_count,
        exclusions=tuple(report.get("exclude_also", [])),
        omissions=tuple(run.get("omit", [])) + tuple(report.get("omit", [])),
    )


def evaluate(base: CoverageRules | None, head: CoverageRules) -> tuple[str, ...]:
    """Compare the head's rules with the base branch's. Pure.

    Args:
        base: The base branch's rules, or None when the base predates the floor file.
        head: The pull request's rules.

    Returns:
        One message per violation; empty when the ratchet holds.
    """
    if base is None:
        return ()
    failures: list[str] = []
    if head.floor < base.floor:
        failures.append(f"coverage floor lowered from {base.floor} to {head.floor}")
    if head.pragma_count > base.pragma_count:
        failures.append(
            f"'{PRAGMA_MARKER}' pragmas grew from {base.pragma_count} to {head.pragma_count}"
        )
    added_exclusions = sorted(set(head.exclusions) - set(base.exclusions))
    if added_exclusions:
        failures.append(f"coverage exclude_also gained {added_exclusions}")
    added_omissions = sorted(set(head.omissions) - set(base.omissions))
    if added_omissions:
        failures.append(f"coverage omit gained {added_omissions}")
    return tuple(failures)


def run_git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run git in the repository root and capture text output."""
    return subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, encoding="utf-8", check=False
    )


def main() -> None:
    """Compare the working tree with the base ref (default origin/main) and exit 1 on a drop."""
    root = Path(run_git(Path.cwd(), "rev-parse", "--show-toplevel").stdout.strip())
    base_ref = os.environ.get("FLOOR_GUARD_BASE", "origin/main")
    if run_git(root, "rev-parse", "--verify", f"{base_ref}^{{commit}}").returncode != 0:
        print(f"cannot read {base_ref}; fetch it before running the floor guard")
        sys.exit(1)

    head = rules_from_texts(
        (root / FLOOR_PATH).read_text(encoding="utf-8"),
        (root / PYPROJECT_PATH).read_text(encoding="utf-8"),
        count_pragmas(run_git(root, "grep", "-c", PRAGMA_MARKER, "--", *SOURCE_PATHS).stdout),
    )
    base_floor = run_git(root, "show", f"{base_ref}:{FLOOR_PATH}")
    base = None
    if base_floor.returncode == 0:
        base = rules_from_texts(
            base_floor.stdout,
            run_git(root, "show", f"{base_ref}:{PYPROJECT_PATH}").stdout,
            count_pragmas(
                run_git(root, "grep", "-c", PRAGMA_MARKER, base_ref, "--", *SOURCE_PATHS).stdout
            ),
        )
    else:
        print(f"{base_ref} has no {FLOOR_PATH}; this change establishes the floor")

    failures = evaluate(base, head)
    for failure in failures:
        print(f"floor guard: {failure}")
    if not failures:
        print(f"floor guard: ratchet holds at {head.floor}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
