"""How many lands a deck plays, which ones, and how many sources of each color that gives.

Seventeen lands unless the curve is low (average mana value under 2.7 with at most two
cards costing five or more), then sixteen. Best-of-one hand smoothing is why seventeen
stays the default. Non-basic lands from the pool that tap for two of the deck's colors go
in first. A splash gets one basic, or two when the deck would otherwise have fewer than
three splash sources. The main colors split the rest by colored pips, with cheap spells
counting 1.5 times, with duals counted toward each color, and each main color the spells
use gets at least six sources. Only lands count as splash
sources: spells that make treasure or fetch a basic are too slow to count on (decision 0006).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from arena_wizard.domain.cards import Card, Color
from arena_wizard.domain.decks import LandEntry
from arena_wizard.engine.mana import color_weight, dependable_colors

BASIC_NAMES = {
    Color.WHITE: "Plains",
    Color.BLUE: "Island",
    Color.BLACK: "Swamp",
    Color.RED: "Mountain",
    Color.GREEN: "Forest",
}
MIN_MAIN_SOURCES = 6


@dataclass(frozen=True, slots=True)
class Manabase:
    """A deck's lands and the sources of each color they provide."""

    lands: tuple[LandEntry, ...]
    sources: dict[Color, int]


def land_count(spells: Sequence[tuple[Card, int]]) -> int:
    """Return 16 for a low curve, otherwise 17. Pure."""
    copies = sum(n for _, n in spells)
    if copies == 0:
        return 17
    average = sum(card.mana_value * n for card, n in spells) / copies
    expensive = sum(n for card, n in spells if card.mana_value >= 5)
    return 16 if average < 2.7 and expensive <= 2 else 17


def build_manabase(
    spells: Sequence[tuple[Card, int]],
    main: tuple[Color, ...],
    splash: Color | None,
    pool_lands: Sequence[tuple[Card, int]],
    total: int,
    splash_sources: int = 3,
) -> Manabase:
    """Choose the lands for a deck. Pure.

    Args:
        spells: The deck's spells with copies.
        main: The two main colors.
        splash: The splash color, if any.
        pool_lands: Non-basic lands in the pool with copies.
        total: How many land slots to fill.
        splash_sources: The splash color's minimum land sources.

    Returns:
        The lands and the resulting sources per color.
    """
    colors = set(main) | ({splash} if splash else set())
    lands: list[LandEntry] = []
    sources = dict.fromkeys(sorted(colors, key=list(BASIC_NAMES).index), 0)
    used = 0
    for card, copies in pool_lands:
        makes = dependable_colors(card) & colors
        if len(makes) >= 2 and used < total:
            take = min(copies, total - used)
            lands.append(LandEntry(card.front_name, None, take))
            used += take
            for color in makes:
                sources[color] += take
    remaining = total - used
    if splash is not None:
        splash_basics = min(max(1, splash_sources - sources[splash]), remaining)
        sources[splash] += splash_basics
        if splash_basics:
            lands.append(LandEntry(BASIC_NAMES[splash], splash, splash_basics))
        remaining -= splash_basics
    weight = color_weight(spells, main)
    counts = _split_basics(weight, {c: sources[c] for c in main}, remaining)
    for color in main:
        if counts[color] > 0:
            lands.append(LandEntry(BASIC_NAMES[color], color, counts[color]))
            sources[color] += counts[color]
    return Manabase(lands=tuple(lands), sources=sources)


def _split_basics(
    weight: dict[Color, float], dual_sources: dict[Color, int], basics: int
) -> dict[Color, int]:
    """Split basics between the two main colors so their sources follow pip weight. Pure.

    Duals already count toward each color's sources. The lighter color gets its share,
    raised to six sources when its spells use it at all; the heavier color gets the rest,
    so the counts always add up to `basics`.
    """
    heavier, lighter = sorted(weight, key=lambda c: (-weight[c], list(BASIC_NAMES).index(c)))
    total_weight = weight[heavier] + weight[lighter]
    share = weight[lighter] / total_weight if total_weight else 0.5
    total_sources = basics + dual_sources[heavier] + dual_sources[lighter]
    wanted = round(share * total_sources) - dual_sources[lighter]
    if weight[lighter] > 0:
        wanted = max(wanted, MIN_MAIN_SOURCES - dual_sources[lighter])
    light = min(max(wanted, 0), basics)
    return {heavier: basics - light, lighter: light}
