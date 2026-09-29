"""A sealed pool as the engine sees it: a multiset of resolved cards plus what went wrong.

The pool is a tuple of (card, count) entries, never a list of repeated cards, and
problems with the input are warnings carried alongside it, never exceptions: the player
is the authority on their own pool, so nothing here blocks building.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from arena_wizard.domain.cards import Card
from arena_wizard.domain.sets import Format


class WarningKind(StrEnum):
    """Why a line or the pool as a whole deserves the player's attention."""

    UNPARSED = "unparsed"
    UNKNOWN_NAME = "unknown_name"
    WRONG_SET = "wrong_set"
    ALTERNATE_PRINTING = "alternate_printing"
    POOL_SIZE = "pool_size"


@dataclass(frozen=True, slots=True)
class ParsedLine:
    """One line of an Arena export: `1 Card Name (SET) 123`."""

    line_no: int
    count: int
    name: str
    set_code: str
    collector_number: str


@dataclass(frozen=True, slots=True)
class ParseWarning:
    """Something the player should look at; never a reason to refuse the pool."""

    kind: WarningKind
    message: str
    line_no: int | None = None
    raw: str = ""
    suggestions: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PoolEntry:
    """A card and how many copies of it."""

    card: Card
    count: int


@dataclass(frozen=True, slots=True)
class Pool:
    """A resolved pool. Basic lands are kept apart because Arena supplies them freely."""

    set_code: str
    format: Format
    entries: tuple[PoolEntry, ...]
    basics: tuple[PoolEntry, ...]
    warnings: tuple[ParseWarning, ...]

    @property
    def nonbasic_count(self) -> int:
        """How many non-basic cards the pool holds, counting copies."""
        return sum(entry.count for entry in self.entries)
