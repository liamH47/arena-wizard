"""The evaluation set's records: real pools, the decks their owners built, and results.

These are derived from 17Lands public game files (CC BY 4.0; see `backend/eval/NOTICE`).
One record per pool: the non-basic pool, every build the player registered (deck, colors,
games, wins), and the player's skill buckets.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class BuildRecord:
    """One deck a player registered for a pool, and how it did."""

    build_index: int
    main_colors: str
    splash_colors: str
    deck: Mapping[str, int]
    games: int
    wins: int


@dataclass(frozen=True, slots=True)
class PoolRecord:
    """One real sealed pool and everything the player did with it."""

    draft_id: str
    first_day: dt.date
    pool: Mapping[str, int]
    builds: tuple[BuildRecord, ...]
    win_rate_bucket: float | None
    games_bucket: int | None

    @property
    def first_build(self) -> BuildRecord:
        """The deck the player registered first."""
        return self.builds[0]

    @property
    def games(self) -> int:
        """Games played with the pool across every build."""
        return sum(b.games for b in self.builds)

    @property
    def wins(self) -> int:
        """Games won with the pool across every build."""
        return sum(b.wins for b in self.builds)


def record_to_json(record: PoolRecord) -> str:
    """One compact, deterministic JSON line. Pure."""
    document = {
        "draft_id": record.draft_id,
        "first_day": record.first_day.isoformat(),
        "pool": dict(sorted(record.pool.items())),
        "builds": [
            {
                "build_index": b.build_index,
                "main_colors": b.main_colors,
                "splash_colors": b.splash_colors,
                "deck": dict(sorted(b.deck.items())),
                "games": b.games,
                "wins": b.wins,
            }
            for b in record.builds
        ],
        "win_rate_bucket": record.win_rate_bucket,
        "games_bucket": record.games_bucket,
    }
    return json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def record_from_json(line: str) -> PoolRecord:
    """Parse one line written by `record_to_json`."""
    raw: dict[str, Any] = json.loads(line)
    return PoolRecord(
        draft_id=raw["draft_id"],
        first_day=dt.date.fromisoformat(raw["first_day"]),
        pool=raw["pool"],
        builds=tuple(
            BuildRecord(
                build_index=b["build_index"],
                main_colors=b["main_colors"],
                splash_colors=b["splash_colors"],
                deck=b["deck"],
                games=b["games"],
                wins=b["wins"],
            )
            for b in raw["builds"]
        ),
        win_rate_bucket=raw["win_rate_bucket"],
        games_bucket=raw["games_bucket"],
    )
