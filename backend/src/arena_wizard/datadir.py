"""Where private data lives, and what day it is in UTC.

Pasted data (decision 0005) is private: it lives in a data directory outside every git
work tree, so it can never be committed by accident. Only `cli.main` resolves the
directory; every function that reads or writes it takes the path as a required argument,
so a test that forgets it fails instead of touching the owner's real data (decision 0007).
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

DATA_DIR_ENV = "ARENA_WIZARD_DATA_DIR"
PRIVATE_MARKER = "arena-wizard-" + "private"
"""Written into every private file. Built by concatenation so that this source file does
not itself contain the marker the floor guard searches tracked files for."""


class DataDirError(ValueError):
    """The configured data directory would put private data at risk."""


def utc_day(now: dt.datetime) -> dt.date:
    """The UTC calendar day of an aware timestamp. Pure.

    Raises:
        ValueError: The timestamp has no time zone, so its UTC day is unknowable.
    """
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("a naive timestamp has no UTC day; pass an aware datetime")
    return now.astimezone(dt.UTC).date()


def git_work_tree(path: Path) -> Path | None:
    """The git work tree containing `path`, or None. Looks only at the file system."""
    for candidate in (path, *path.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def resolve_data_dir(env_value: str | None, home: Path) -> Path:
    """Choose the private data directory.

    Args:
        env_value: The value of ARENA_WIZARD_DATA_DIR, if set.
        home: The user's home directory, for the default.

    Returns:
        The absolute directory; it need not exist yet.

    Raises:
        DataDirError: The directory is inside a git work tree.
    """
    path = Path(env_value) if env_value else home / ".local" / "share" / "arena-wizard"
    path = path.resolve()
    tree = git_work_tree(path)
    if tree is not None:
        raise DataDirError(
            f"{path} is inside the git work tree {tree}; private data must live outside "
            f"every repository. Set {DATA_DIR_ENV} to a directory outside it."
        )
    return path
