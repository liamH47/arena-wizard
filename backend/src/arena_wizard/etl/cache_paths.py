"""Where the download cache keeps each 17Lands public file and its counts.

Kept apart from `game_cache`, which downloads, so that code which only needs to know
whether a file is cached (the paste importer) imports no HTTP client (decision 0007).
"""

from __future__ import annotations

import os
from pathlib import Path

from arena_wizard.domain.sets import EventType


def cache_dir() -> Path:
    """Where downloaded files and counts are kept."""
    configured = os.environ.get("ARENA_WIZARD_CACHE_DIR")
    return Path(configured) if configured else Path.home() / ".cache" / "arena-wizard"


def counts_path(root: Path, set_code: str, event_type: EventType) -> Path:
    """Where the counts for one file are cached."""
    return root / "17lands" / f"{set_code}.{event_type.value}.counts.json"


def file_path(root: Path, set_code: str, event_type: EventType) -> Path:
    """Where the downloaded file itself is cached."""
    return root / "17lands" / f"game_data_public.{set_code}.{event_type.value}.csv.gz"
