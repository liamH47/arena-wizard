"""Card and color-pair statistics, as counts, with rates derived on demand.

Counts are stored rather than rates so that windows can be summed exactly and so that a
rate with no games behind it is None, never zero.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from dataclasses import dataclass, field


def rate(wins: int, games: int) -> float | None:
    """Return wins / games, or None when there are no games."""
    return wins / games if games else None


@dataclass(frozen=True, slots=True)
class CardCounts:
    """One card's game counts in a window, keyed by the 17Lands (front-face) name.

    `gih` counts games where the card was in the opening hand or drawn; `gns` counts games
    where it was in the deck but never seen; `played` counts games where it was in the deck.
    """

    games_gih: int = 0
    wins_gih: int = 0
    games_gns: int = 0
    wins_gns: int = 0
    games_played: int = 0
    wins_played: int = 0

    def __add__(self, other: CardCounts) -> CardCounts:
        """Sum two windows."""
        return CardCounts(
            self.games_gih + other.games_gih,
            self.wins_gih + other.wins_gih,
            self.games_gns + other.games_gns,
            self.wins_gns + other.wins_gns,
            self.games_played + other.games_played,
            self.wins_played + other.wins_played,
        )

    @property
    def gih_wr(self) -> float | None:
        """Win rate in games where the card was in hand (opening hand or drawn)."""
        return rate(self.wins_gih, self.games_gih)

    @property
    def gns_wr(self) -> float | None:
        """Win rate in games where the card was in the deck but not seen."""
        return rate(self.wins_gns, self.games_gns)


@dataclass(frozen=True, slots=True)
class PairCounts:
    """Games and wins for decks whose main colors are exactly this code, e.g. "BG"."""

    games: int = 0
    wins: int = 0

    def __add__(self, other: PairCounts) -> PairCounts:
        """Sum two windows."""
        return PairCounts(self.games + other.games, self.wins + other.wins)

    @property
    def win_rate(self) -> float | None:
        """Wins / games, or None with no games."""
        return rate(self.wins, self.games)


@dataclass(frozen=True, slots=True)
class SourceRef:
    """Where a set of numbers came from, shown next to every number derived from it."""

    label: str
    first_day: dt.date | None
    last_day: dt.date | None
    content_sha256: str | None
    games: int


@dataclass(frozen=True, slots=True)
class Snapshot:
    """Every card's and every color pair's counts from one source over one window.

    `unrated` holds in-hand games for cards whose win rate the source left blank (17Lands
    blanks thin samples): too few to rate, but they still say how often the card is played.
    """

    set_code: str
    source: SourceRef
    cards: Mapping[str, CardCounts]
    pairs: Mapping[str, PairCounts]
    unrated: Mapping[str, int] = field(default_factory=dict)
