"""Read the base branch's committed evaluation report, failing closed.

An unreadable base ref is an error, never a silent skip: a shallow CI checkout has no
`origin/main`, and treating that as "no base" would switch the regression gate off
without anyone noticing. Only a base that exists but predates the report file is the
bootstrap case.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from arena_wizard.devtools.floor_guard import Git, run_git

REPORT_PATH = "backend/eval/report.json"


class BaseUnavailable(RuntimeError):
    """The base ref cannot be read, so the gate cannot compare against it."""


def read_base_report(root: Path, ref: str, git: Git = run_git) -> dict[str, Any] | None:
    """Return the base ref's report, or None when the base predates the report.

    Args:
        root: The repository root.
        ref: The base ref, e.g. "origin/main".
        git: Runs git; injected for tests.

    Raises:
        BaseUnavailable: The ref does not exist in this checkout (fetch it; CI needs
            `fetch-depth: 0`).
    """
    if git(root, "rev-parse", "--verify", f"{ref}^{{commit}}").returncode != 0:
        raise BaseUnavailable(f"cannot read {ref}; fetch it (CI needs fetch-depth: 0)")
    shown = git(root, "show", f"{ref}:{REPORT_PATH}")
    if shown.returncode != 0:
        return None
    report: dict[str, Any] = json.loads(shown.stdout)
    return report
