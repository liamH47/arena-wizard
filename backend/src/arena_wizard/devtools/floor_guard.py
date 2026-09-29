"""CI guard that keeps the coverage gate a ratchet.

Fails a pull request that lowers `coverage_floor.txt`, adds coverage-exclusion pragmas,
widens what coverage skips (exclusions, partial branches, omitted files), changes what it
measures, moves coverage settings into a file this guard does not read, or edits the CI
commands that apply the floor and the evaluation gate. Each of those makes the number look
the same while testing less. It also fails when a file carrying the private-data marker,
which every pasted-data file has, appears in the repository.

All git access goes through `collect_rules` and `check`, which take the git runner as a
parameter and are tested against real temporary repositories; `main` only prints.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from arena_wizard.datadir import PRIVATE_MARKER

PRAGMA_PATTERN = r"#[[:space:]]*pragma[:[:space:]]?[[:space:]]*no[[:space:]]*(cover|branch)"
"""Every spelling coverage.py honours (it matches case-insensitively), as a git-grep ERE."""

FLOOR_PATH = "backend/coverage_floor.txt"
PYPROJECT_PATH = "backend/pyproject.toml"
CI_PATH = ".github/workflows/ci.yml"
SOURCE_PATHS = ("backend/src", "backend/tests")
SHADOWING_CONFIG_PATHS = ("backend/.coveragerc", "backend/setup.cfg", "backend/tox.ini")
"""Coverage reads these before pyproject.toml, so settings there would bypass the guard."""

CI_GATE_COMMAND = 'uv run pytest --cov --cov-fail-under="$(cat coverage_floor.txt)"'
EVAL_GATE_COMMAND = "uv run arena-wizard eval run --check --base"
"""The evaluation gate (decision 0006); dropping it would merge unmeasured scoring changes."""
CI_GATE_COMMANDS = (CI_GATE_COMMAND, EVAL_GATE_COMMAND)

Git = Callable[..., "subprocess.CompletedProcess[str]"]


class GuardError(RuntimeError):
    """Git failed in a way that makes the comparison meaningless; fail closed."""


@dataclass(frozen=True, slots=True)
class CoverageRules:
    """Everything that decides how much code the coverage gate actually measures."""

    floor: int
    pragma_count: int
    exclusions: tuple[str, ...]
    partial_branches: tuple[str, ...]
    omissions: tuple[str, ...]
    scope: tuple[str, ...]


def run_git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run git in `root` and capture text output. Never raises on a non-zero exit."""
    return subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, encoding="utf-8", check=False
    )


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


def count_pragmas(grep: subprocess.CompletedProcess[str]) -> int:
    """Sum the counts from a `git grep -c` run, whose lines end in `:count`.

    Args:
        grep: The completed git grep.

    Returns:
        The total number of matching lines; 0 when git grep found none.

    Raises:
        GuardError: git grep failed, which must not be read as "no pragmas".
    """
    if grep.returncode == 1:
        return 0
    if grep.returncode != 0:
        raise GuardError(f"git grep failed ({grep.returncode}): {grep.stderr.strip()}")
    return sum(int(line.rsplit(":", 1)[1]) for line in grep.stdout.splitlines() if line.strip())


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
        exclusions=tuple(report.get("exclude_also", [])) + tuple(report.get("exclude_lines", [])),
        partial_branches=tuple(report.get("partial_branches", []))
        + tuple(report.get("partial_branches_also", [])),
        omissions=tuple(run.get("omit", [])) + tuple(report.get("omit", [])),
        scope=tuple(run.get("source", []))
        + tuple(run.get("include", []))
        + tuple(report.get("include", [])),
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
            f"coverage-exclusion pragmas grew from {base.pragma_count} to {head.pragma_count}"
        )
    for label, before, after in (
        ("exclusions", base.exclusions, head.exclusions),
        ("partial branches", base.partial_branches, head.partial_branches),
        ("omit", base.omissions, head.omissions),
    ):
        added = sorted(set(after) - set(before))
        if added:
            failures.append(f"coverage {label} gained {added}")
    if head.scope != base.scope:
        failures.append(f"coverage scope changed from {list(base.scope)} to {list(head.scope)}")
    return tuple(failures)


def _read(root: Path, ref: str | None, path: str, git: Git) -> str | None:
    """Read a file from the working tree (ref None) or from a git ref; None when absent."""
    if ref is None:
        file = root / path
        return file.read_text(encoding="utf-8") if file.is_file() else None
    shown = git(root, "show", f"{ref}:{path}")
    return shown.stdout if shown.returncode == 0 else None


def collect_rules(root: Path, ref: str | None, git: Git = run_git) -> CoverageRules | None:
    """Read the coverage rules from the working tree or from a git ref.

    Args:
        root: The repository root.
        ref: A git ref, or None for the working tree (tracked and untracked files).
        git: Runs git; injected for tests.

    Returns:
        The rules, or None when the floor file does not exist there.

    Raises:
        GuardError: git grep failed.
    """
    floor_text = _read(root, ref, FLOOR_PATH, git)
    if floor_text is None:
        return None
    flags = ["--untracked"] if ref is None else []
    revision = [] if ref is None else [ref]
    grep = git(
        root, "grep", "-E", "-i", "-c", *flags, "-e", PRAGMA_PATTERN, *revision, "--", *SOURCE_PATHS
    )
    return rules_from_texts(
        floor_text, _read(root, ref, PYPROJECT_PATH, git) or "", count_pragmas(grep)
    )


def structural_failures(root: Path) -> tuple[str, ...]:
    """Check the working tree for ways around the guard that a rules diff cannot see.

    Args:
        root: The repository root.

    Returns:
        One message per problem.
    """
    failures = [
        f"{path} exists; coverage settings belong in {PYPROJECT_PATH}"
        for path in SHADOWING_CONFIG_PATHS
        if (root / path).exists()
    ]
    ci = _read(root, None, CI_PATH, run_git)
    failures += [
        f"{CI_PATH} no longer runs `{command}`"
        for command in CI_GATE_COMMANDS
        if ci is None or command not in ci
    ]
    return tuple(failures)


def private_data_failures(root: Path, git: Git = run_git) -> tuple[str, ...]:
    """Find files in the repository that carry the private-data marker (decision 0007).

    Every file the private paste store writes carries `PRIVATE_MARKER`, so one showing up
    in the work tree (tracked, or untracked and not ignored) is pasted data about to be
    committed.

    Args:
        root: The repository root.
        git: Runs git; injected for tests.

    Returns:
        One message naming the files, or nothing.

    Raises:
        GuardError: git grep failed, which must not be read as "no private data".
    """
    grep = git(root, "grep", "-l", "-F", "--untracked", "-e", PRIVATE_MARKER)
    if grep.returncode == 1:
        return ()
    if grep.returncode != 0:
        raise GuardError(f"git grep failed ({grep.returncode}): {grep.stderr.strip()}")
    files = sorted(line.strip() for line in grep.stdout.splitlines() if line.strip())
    return (f"private pasted data is in the repository: {', '.join(files)}",)


DATABASE_PATTERNS = ("*.db", "*.sqlite", "*.sqlite3")


def database_file_failures(root: Path, git: Git = run_git) -> tuple[str, ...]:
    """Find database files git would commit. The web app's database holds pasted data,
    and its rows carry no marker, so any committed database file is refused (decision 0008).

    Raises:
        GuardError: git ls-files failed.
    """
    listed = git(
        root, "ls-files", "--cached", "--others", "--exclude-standard", "--", *DATABASE_PATTERNS
    )
    if listed.returncode != 0:
        raise GuardError(f"git ls-files failed ({listed.returncode}): {listed.stderr.strip()}")
    files = sorted(line.strip() for line in listed.stdout.splitlines() if line.strip())
    return (f"database files would be committed: {', '.join(files)}",) if files else ()


def check(root: Path, base_ref: str, git: Git = run_git) -> tuple[str, ...]:
    """Run every check of the working tree against a base ref.

    Args:
        root: The repository root.
        base_ref: The ref to compare with, e.g. "origin/main".
        git: Runs git; injected for tests.

    Returns:
        One message per violation; empty when the ratchet holds.
    """
    if git(root, "rev-parse", "--verify", f"{base_ref}^{{commit}}").returncode != 0:
        return (f"cannot read {base_ref}; fetch it before running the floor guard",)
    head = collect_rules(root, None, git)
    if head is None:
        return (f"{FLOOR_PATH} is missing",)
    return (
        structural_failures(root)
        + private_data_failures(root, git)
        + database_file_failures(root, git)
        + evaluate(collect_rules(root, base_ref, git), head)
    )


def main() -> None:
    """Compare the working tree with FLOOR_GUARD_BASE (default origin/main); exit 1 on a drop."""
    root = Path(run_git(Path.cwd(), "rev-parse", "--show-toplevel").stdout.strip())
    failures = check(root, os.environ.get("FLOOR_GUARD_BASE", "origin/main"))
    for failure in failures:
        print(f"floor guard: {failure}")
    if not failures:
        print("floor guard: ratchet holds")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
