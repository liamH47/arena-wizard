"""Card identity and printed characteristics, as stored in the committed card tables.

A `Card` is one Arena printing: the same card in the main set and on a bonus sheet is two
`Card` objects that share an `oracle_id` and a `front_name`. 17Lands keys its statistics
by front name, never by the full `A // B` name, so `front_name` is the join key between a
pool and its statistics.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Color(StrEnum):
    """One of the five colors, in WUBRG order."""

    WHITE = "W"
    BLUE = "U"
    BLACK = "B"
    RED = "R"
    GREEN = "G"


WUBRG: tuple[Color, ...] = (Color.WHITE, Color.BLUE, Color.BLACK, Color.RED, Color.GREEN)


class Rarity(StrEnum):
    """Printed rarity. Bonus-sheet cards keep the rarity Scryfall gives them."""

    COMMON = "common"
    UNCOMMON = "uncommon"
    RARE = "rare"
    MYTHIC = "mythic"
    SPECIAL = "special"
    BONUS = "bonus"


def sort_colors(colors: tuple[Color, ...] | list[Color]) -> tuple[Color, ...]:
    """Return the distinct colors in WUBRG order.

    Args:
        colors: Colors in any order, possibly repeated.

    Returns:
        The distinct colors ordered W, U, B, R, G.
    """
    present = set(colors)
    return tuple(color for color in WUBRG if color in present)


@dataclass(frozen=True, slots=True)
class CardFace:
    """One face of a multi-face card (adventure, prepare, split, transform)."""

    name: str
    mana_cost: str
    type_line: str
    oracle_text: str
    power: str | None
    toughness: str | None


@dataclass(frozen=True, slots=True)
class Card:
    """One Arena printing of a card, trimmed to what the engine and the UI need."""

    scryfall_id: str
    oracle_id: str
    arena_id: int | None
    name: str
    front_name: str
    layout: str
    set_code: str
    collector_number: str
    rarity: Rarity
    mana_cost: str
    mana_value: float
    type_line: str
    oracle_text: str
    power: str | None
    toughness: str | None
    colors: tuple[Color, ...]
    color_identity: tuple[Color, ...]
    produced_mana: tuple[str, ...]
    faces: tuple[CardFace, ...]
    image_uri: str | None
    artist: str | None
    released_at: str

    @property
    def is_basic(self) -> bool:
        """True for the five basic lands (and snow basics), which Arena supplies freely."""
        return self.type_line.startswith("Basic ")
