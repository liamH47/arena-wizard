"""Mana costs: which colors a spell needs, how many of each, and whether a deck can cast it.

Castability is decided from the mana symbols, never from color identity, so a hybrid card
joins every pair that can pay for it. For a two-part card (adventure, prepare) the front
face is the spell the deck is built around.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from functools import cache

from arena_wizard.domain.cards import WUBRG, Card, Color

_SYMBOL = re.compile(r"\{([^}]+)\}")
_COLOR_LETTERS = {color.value for color in WUBRG}


@dataclass(frozen=True, slots=True)
class ManaCost:
    """The colored requirements of a cost.

    `pips` are single-color symbols that must be paid with that color. `hybrid` holds one
    set of acceptable colors per two-color hybrid symbol. Generic, colorless, X, snow,
    Phyrexian (payable with life), and two-generic hybrid symbols impose no color need.
    """

    pips: Mapping[Color, int]
    hybrid: tuple[frozenset[Color], ...]


def parse_mana_cost(cost: str) -> ManaCost:
    """Parse a Scryfall mana cost such as "{1}{W}{W/B}". Pure.

    Args:
        cost: One face's mana cost.

    Returns:
        Its colored requirements.
    """
    pips: Counter[Color] = Counter()
    hybrid: list[frozenset[Color]] = []
    for symbol in _SYMBOL.findall(cost):
        parts = symbol.split("/")
        if "P" in parts:
            continue
        colors = [Color(part) for part in parts if part in _COLOR_LETTERS]
        if len(parts) == 1 and len(colors) == 1:
            pips[colors[0]] += 1
        elif len(colors) == 2:
            hybrid.append(frozenset(colors))
    return ManaCost(pips=dict(pips), hybrid=tuple(hybrid))


_SUSPEND = re.compile(r"Suspend \d+\s*[\u2014-]\s*((?:\{[^}]+\})+)")


@cache
def castable_cost(card: Card) -> ManaCost:
    """Return the cost that decides whether a deck can play the card: its front face.

    A spell with no mana cost (Living End) is cast by suspending it, so its suspend cost
    counts; failing that, it needs one source of each of its colors.
    """
    cost = card.faces[0].mana_cost if card.faces else card.mana_cost
    if cost:
        return parse_mana_cost(cost)
    suspend = _SUSPEND.search(card.oracle_text)
    if suspend:
        return parse_mana_cost(suspend.group(1))
    return ManaCost(pips=dict.fromkeys(card.colors, 1), hybrid=())


def can_cast(cost: ManaCost, colors: Iterable[Color]) -> bool:
    """True when every pip's color is available and every hybrid symbol has an option.

    Args:
        cost: The requirements.
        colors: The deck's colors, splash included.

    Returns:
        Whether the deck could ever pay the cost.
    """
    available = set(colors)
    return all(color in available for color in cost.pips) and all(
        options & available for options in cost.hybrid
    )


def requirements(cost: ManaCost, sources: Mapping[Color, int]) -> dict[Color, int]:
    """Resolve hybrid symbols to concrete color needs, using the better-supplied color.

    Args:
        cost: The requirements.
        sources: How many sources of each color the deck has.

    Returns:
        How many sources of each color the spell needs; hybrid symbols go to whichever of
        their colors the deck has more of (ties broken in WUBRG order).
    """
    needs: Counter[Color] = Counter(cost.pips)
    for options in cost.hybrid:
        ordered = [color for color in WUBRG if color in options]
        best = max(ordered, key=lambda color: sources.get(color, 0))
        needs[best] += 1
    return dict(needs)


def color_weight(cards: Iterable[tuple[Card, int]], colors: Iterable[Color]) -> dict[Color, float]:
    """Total colored pips per color across cards, weighting cheap spells 1.5 times.

    Cheap spells need their colors early, so they pull the basic split harder.

    Args:
        cards: (card, copies) pairs.
        colors: The colors to count.

    Returns:
        A weight per color, zero for colors no card asks for.
    """
    wanted = list(colors)
    weight = dict.fromkeys(wanted, 0.0)
    for card, copies in cards:
        cost = castable_cost(card)
        factor = copies * (1.5 if card.mana_value < 4 else 1.0)
        for color, count in cost.pips.items():
            if color in weight:
                weight[color] += count * factor
        for options in cost.hybrid:
            shared = [color for color in wanted if color in options]
            for color in shared:
                weight[color] += factor / len(shared)
    return weight


RESTRICTED_MANA = ("spend this mana only", "choose a color")
"""Lands whose colored mana is conditional (Great Hall of the Biblioplex) or a single color
chosen on entry (Room of Refuge) do not count as sources of every color they list."""


def dependable_colors(card: Card) -> set[Color]:
    """The colors a land can always produce for any spell."""
    text = card.oracle_text.lower()
    if any(phrase in text for phrase in RESTRICTED_MANA):
        return set()
    return {Color(c) for c in card.produced_mana if c in "WUBRG"}
