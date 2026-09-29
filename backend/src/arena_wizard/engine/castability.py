"""How likely a deck is to cast a spell on curve, and how far short of a baseline it falls.

The chance of having at least k sources of a color by the turn after the spell's mana
value, on the play, is hypergeometric. Several colors are treated as independent, a small
overestimate that is the same for every deck compared. The consistency term charges the
shortfall against a baseline of 8 sources per needed color, which is what a normal 9/8
two-color deck has, so ordinary decks pay nothing and splashes pay their real price.
"""

from __future__ import annotations

from collections.abc import Mapping
from math import comb

from arena_wizard.domain.cards import Color

OPENING_HAND = 7


def at_least(successes: int, population: int, sources: int, draws: int) -> float:
    """P(at least `successes` sources among `draws` cards from a deck). Pure.

    Args:
        successes: How many sources are needed.
        population: Deck size.
        sources: Sources of the color in the deck.
        draws: Cards seen.

    Returns:
        The probability, 1.0 when nothing is needed and 0.0 when it is impossible.
    """
    if successes <= 0:
        return 1.0
    draws = min(draws, population)
    total = comb(population, draws)
    miss = sum(
        comb(sources, k) * comb(population - sources, draws - k)
        for k in range(min(successes, sources + 1))
    )
    return 1.0 - miss / total


def cards_seen_on_curve(mana_value: float) -> int:
    """Cards seen by the turn after the spell's mana value, on the play (no draw turn 1)."""
    return OPENING_HAND + max(int(mana_value), 1)


def cast_probability(
    needs: Mapping[Color, int], sources: Mapping[Color, int], mana_value: float, deck_size: int
) -> float:
    """P(every color need is met on curve), treating colors as independent. Pure."""
    draws = cards_seen_on_curve(mana_value)
    probability = 1.0
    for color, count in needs.items():
        probability *= at_least(count, deck_size, sources.get(color, 0), draws)
    return probability


def shortfall(
    needs: Mapping[Color, int],
    sources: Mapping[Color, int],
    mana_value: float,
    *,
    baseline_sources: int,
    deck_size: int,
    scale: float,
) -> float:
    """How much less castable the spell is than with `baseline_sources` of each color. Pure.

    Args:
        needs: Sources needed per color.
        sources: Sources the deck has per color.
        mana_value: The spell's mana value.
        baseline_sources: The source count an ordinary deck has for each color.
        deck_size: Cards in the deck.
        scale: Points per unit of probability.

    Returns:
        Zero when the deck matches or beats the baseline; otherwise the shortfall in points.
    """
    baseline = cast_probability(
        needs, dict.fromkeys(needs, baseline_sources), mana_value, deck_size
    )
    actual = cast_probability(needs, sources, mana_value, deck_size)
    return scale * max(0.0, baseline - actual)
