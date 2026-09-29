from __future__ import annotations

import pytest

from arena_wizard.domain.cards import Color
from arena_wizard.domain.decks import LandEntry, ScoredDeck
from arena_wizard.domain.pool import PoolEntry
from arena_wizard.domain.stats import CardCounts, PairCounts, rate
from tests.unit.test_lands import card


def _deck(
    splash: Color | None = None,
    gap_to_next: float | None = None,
    gap_se: float | None = None,
) -> ScoredDeck:
    return ScoredDeck(
        colors="BG",
        splash=splash,
        spells=(PoolEntry(card("One", "{B}", 1.0), 2), PoolEntry(card("Two", "{G}", 1.0), 21)),
        lands=(LandEntry("Swamp", Color.BLACK, 8), LandEntry("Forest", Color.GREEN, 9)),
        total=10.0,
        total_se=1.0,
        terms=(),
        values=(),
        gap_to_next=gap_to_next,
        gap_se=gap_se,
    )


def test_a_deck_label_names_its_colors_and_a_lowercase_splash() -> None:
    assert _deck().label == "BG"
    assert _deck(Color.RED).label == "BG+r"


def test_spell_and_land_counts_include_copies() -> None:
    assert (_deck().spell_count, _deck().land_count) == (23, 17)


@pytest.mark.parametrize(
    ("gap", "se", "toss_up"),
    [(None, 1.0, False), (0.5, None, False), (0.5, 1.0, True), (1.0, 1.0, False)],
)
def test_a_gap_under_one_standard_error_is_a_toss_up(
    gap: float | None, se: float | None, toss_up: bool
) -> None:
    assert _deck(gap_to_next=gap, gap_se=se).is_toss_up is toss_up


def test_a_rate_without_games_is_none_not_zero() -> None:
    assert rate(0, 0) is None
    assert rate(3, 4) == 0.75


def test_card_counts_add_field_by_field_and_derive_rates() -> None:
    total = CardCounts(10, 6, 4, 1, 14, 7) + CardCounts(10, 4, 4, 3, 14, 7)
    assert total == CardCounts(20, 10, 8, 4, 28, 14)
    assert (total.gih_wr, total.gns_wr) == (0.5, 0.5)
    assert (CardCounts().gih_wr, CardCounts().gns_wr) == (None, None)


def test_pair_counts_add_and_derive_a_win_rate() -> None:
    assert PairCounts(10, 6) + PairCounts(30, 14) == PairCounts(40, 20)
    assert PairCounts(40, 20).win_rate == 0.5
    assert PairCounts().win_rate is None
