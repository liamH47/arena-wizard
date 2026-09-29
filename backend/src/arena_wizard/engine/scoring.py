"""The deck objective S and its breakdown.

S = card quality (sum of card values) + color-pair strength + bombs (the strongest counts
1, the next two thirds, and so on) - distance from the creature window + capped removal +
capped two- and three-drops - excess expensive spells - castability shortfall - a charge
per splashed card. Every term is a sum over cards or a function of counts, so `swap`
updates a DeckState in constant time; `tests/unit/test_scoring.py` checks it against a
full rescore.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterable
from dataclasses import dataclass

from arena_wizard.domain.decks import ScoreTerm
from arena_wizard.domain.scoring import ScoringConfig


@dataclass(frozen=True, slots=True)
class SpellFacts:
    """One copy of a spell, reduced to what the objective needs."""

    key: str
    name: str
    q: float
    se: float
    creature: bool
    removal: bool
    mana_value: float
    shortfall: float
    bomb: float | None
    splash: bool


@dataclass(frozen=True, slots=True)
class DeckState:
    """Running totals over a deck's spell copies."""

    sum_q: float = 0.0
    sum_shortfall: float = 0.0
    creatures: int = 0
    removal: int = 0
    two_drops: int = 0
    three_drops: int = 0
    five_plus: int = 0
    splash_cards: int = 0
    bombs: tuple[float, ...] = ()

    def _shift(self, spell: SpellFacts, sign: int) -> DeckState:
        """Add (sign 1) or remove (sign -1) one spell copy."""
        bombs = list(self.bombs)
        if spell.bomb is not None:
            if sign > 0:
                bombs.append(spell.bomb)
            else:
                bombs.remove(spell.bomb)
        return dataclasses.replace(
            self,
            sum_q=self.sum_q + sign * spell.q,
            sum_shortfall=self.sum_shortfall + sign * spell.shortfall,
            creatures=self.creatures + sign * spell.creature,
            removal=self.removal + sign * spell.removal,
            two_drops=self.two_drops + sign * (spell.creature and spell.mana_value <= 2),
            three_drops=self.three_drops + sign * (spell.creature and spell.mana_value == 3),
            five_plus=self.five_plus + sign * (spell.mana_value >= 5),
            splash_cards=self.splash_cards + sign * spell.splash,
            bombs=tuple(sorted(bombs, reverse=True)),
        )

    def add(self, spell: SpellFacts) -> DeckState:
        """Return the state with one more copy of `spell`."""
        return self._shift(spell, 1)

    def swap(self, out: SpellFacts, into: SpellFacts) -> DeckState:
        """Return the state with `out` replaced by `into`."""
        return self._shift(out, -1)._shift(into, 1)


def state_of(spells: Iterable[SpellFacts]) -> DeckState:
    """Build a state from scratch. Pure."""
    state = DeckState()
    for spell in spells:
        state = state.add(spell)
    return state


def terms(state: DeckState, pair_points: float, config: ScoringConfig) -> tuple[ScoreTerm, ...]:
    """Break a deck's score into named terms. Pure.

    Args:
        state: The deck's totals.
        pair_points: The color pair's strength, in win-rate points above the pair mean.
        config: Weights and targets.

    Returns:
        One term per part of the objective, in a fixed order.
    """
    w, t = config.weights, config.targets
    bomb_raw = sum(1.5**-rank for rank in range(len(state.bombs)))
    creature_gap = max(0, t.creatures_low - state.creatures) + max(
        0, state.creatures - t.creatures_high
    )
    raw = {
        "card_quality": (state.sum_q, w.card_quality, "sum of card values"),
        "pair_strength": (pair_points, w.pair_strength, "color pair above the pair mean"),
        "bombs": (bomb_raw, w.bomb, f"{len(state.bombs)} bombs"),
        "creature_balance": (
            -creature_gap,
            w.creature_balance,
            f"{state.creatures} creatures (target {t.creatures_low} to {t.creatures_high})",
        ),
        "removal": (min(state.removal, t.removal_cap), w.removal, f"{state.removal} removal"),
        "two_drops": (
            min(state.two_drops, t.two_drop_cap),
            w.two_drop,
            f"{state.two_drops} creatures costing 2 or less",
        ),
        "three_drops": (
            min(state.three_drops, t.three_drop_cap),
            w.three_drop,
            f"{state.three_drops} creatures costing 3",
        ),
        "top_end": (
            -max(0, state.five_plus - t.max_five_plus),
            w.top_end,
            f"{state.five_plus} spells costing 5 or more",
        ),
        "consistency": (-state.sum_shortfall, w.consistency, "castability shortfall"),
        "splash": (-state.splash_cards, w.splash_card, f"{state.splash_cards} splashed cards"),
    }
    return tuple(
        ScoreTerm(name=name, raw=value, weight=weight, contribution=value * weight, detail=detail)
        for name, (value, weight, detail) in raw.items()
    )


def total(state: DeckState, pair_points: float, config: ScoringConfig) -> float:
    """The deck's score, equal to the sum of `terms` but without building them. Pure.

    This runs thousands of times per pool inside the builder's hill climb.
    """
    w, t = config.weights, config.targets
    creature_gap = max(0, t.creatures_low - state.creatures) + max(
        0, state.creatures - t.creatures_high
    )
    return (
        w.card_quality * state.sum_q
        + w.pair_strength * pair_points
        + w.bomb * sum(1.5**-rank for rank in range(len(state.bombs)))
        - w.creature_balance * creature_gap
        + w.removal * min(state.removal, t.removal_cap)
        + w.two_drop * min(state.two_drops, t.two_drop_cap)
        + w.three_drop * min(state.three_drops, t.three_drop_cap)
        - w.top_end * max(0, state.five_plus - t.max_five_plus)
        - w.consistency * state.sum_shortfall
        - w.splash_card * state.splash_cards
    )
