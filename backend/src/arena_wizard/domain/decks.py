"""Candidate decks, their scores, and the breakdown that explains each score."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from arena_wizard.domain.cards import Color
from arena_wizard.domain.pool import PoolEntry


class ValueBasis(StrEnum):
    """What a card's value rests on. Explanations branch on this, never on whether some
    snapshot happens to exist (decision 0007)."""

    WIN_RATES = "win rates"
    DRAFT_PROXY = "draft proxy"
    GRADES = "grades"
    RARITY_GRADE = "rarity average of grades"
    RARITY = "rarity average"
    NONE = "no data"


@dataclass(frozen=True, slots=True)
class LayerShare:
    """How much of a value one source carries, as a share of the final weight."""

    name: str
    share: float


@dataclass(frozen=True, slots=True)
class CardValue:
    """What one card is worth to the engine, and how sure it is.

    `q` is in points of game-in-hand win rate above the format mean. `observed` is the raw
    game-in-hand win rate, `used` the shrunk one, and `prior_share` how much of the value
    is the prior. `layers` says how much each source carries and `grades` lists each
    reviewer's own grade, when the value came from the event-mode chain.
    """

    name: str
    q: float
    observed: float | None
    used: float | None
    prior_share: float | None
    games: int
    source: str
    se: float
    basis: ValueBasis = ValueBasis.WIN_RATES
    layers: tuple[LayerShare, ...] = ()
    grades: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class LandEntry:
    """A land slot: a basic (by color) or a non-basic land from the pool."""

    name: str
    color: Color | None
    count: int


@dataclass(frozen=True, slots=True)
class ScoreTerm:
    """One named part of a deck's score, with where its number came from."""

    name: str
    raw: float
    weight: float
    contribution: float
    detail: str


@dataclass(frozen=True, slots=True)
class ScoredDeck:
    """A legal 40-card deck, its score, and everything needed to explain it."""

    colors: str
    splash: Color | None
    spells: tuple[PoolEntry, ...]
    lands: tuple[LandEntry, ...]
    total: float
    total_se: float
    terms: tuple[ScoreTerm, ...]
    values: tuple[CardValue, ...]
    sources: tuple[tuple[Color, int], ...] = ()
    explanations: tuple[str, ...] = ()
    gap_to_next: float | None = None
    gap_se: float | None = None

    @property
    def label(self) -> str:
        """The deck's colors, with the splash if there is one: "BG" or "BG+r"."""
        return self.colors if self.splash is None else f"{self.colors}+{self.splash.lower()}"

    @property
    def spell_count(self) -> int:
        """Non-land cards, counting copies."""
        return sum(entry.count for entry in self.spells)

    @property
    def land_count(self) -> int:
        """Land slots, counting copies."""
        return sum(land.count for land in self.lands)

    @property
    def is_toss_up(self) -> bool:
        """True when the next deck is within one standard error of this one."""
        return (
            self.gap_to_next is not None
            and self.gap_se is not None
            and (self.gap_to_next < self.gap_se)
        )
