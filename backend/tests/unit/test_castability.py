from __future__ import annotations

from math import comb
from typing import TypedDict

import pytest

from arena_wizard.domain.cards import Color
from arena_wizard.engine.castability import (
    at_least,
    cards_seen_on_curve,
    cast_probability,
    shortfall,
)

W, U, B = Color.WHITE, Color.BLUE, Color.BLACK


class Baseline(TypedDict):
    baseline_sources: int
    deck_size: int
    scale: float


BASELINE = Baseline(baseline_sources=8, deck_size=40, scale=10.0)


def test_at_least_matches_a_hand_computed_hypergeometric() -> None:
    # One or more of 8 sources in 9 cards from 40: 1 - C(32,9)/C(40,9).
    assert at_least(1, 40, 8, 9) == pytest.approx(1 - comb(32, 9) / comb(40, 9))


def test_needing_nothing_is_certain_and_needing_more_than_exist_is_impossible() -> None:
    assert at_least(0, 40, 0, 9) == 1.0
    assert at_least(3, 40, 2, 9) == 0.0


def test_cards_seen_on_curve_is_seven_plus_the_turn_before_the_draw_step() -> None:
    assert cards_seen_on_curve(2) == 9
    assert cards_seen_on_curve(0) == 8
    assert cards_seen_on_curve(4.0) == 11


def test_multiple_colors_multiply_as_independent_events() -> None:
    both = cast_probability({W: 1, B: 1}, {W: 8, B: 8}, 2, 40)
    assert both == pytest.approx(at_least(1, 40, 8, 9) ** 2)


def test_an_ordinary_nine_eight_deck_pays_nothing_for_a_double_pip_two_drop() -> None:
    assert shortfall({W: 2}, {W: 8, U: 9}, 2, **BASELINE) == 0.0
    assert shortfall({W: 2}, {W: 10}, 2, **BASELINE) == 0.0


def test_a_splash_off_three_sources_pays_for_its_lower_cast_chance() -> None:
    expected = 10.0 * (at_least(1, 40, 8, 11) - at_least(1, 40, 3, 11))
    assert shortfall({B: 1}, {W: 8, U: 6, B: 3}, 4, **BASELINE) == pytest.approx(expected)
    assert expected > 2.0
