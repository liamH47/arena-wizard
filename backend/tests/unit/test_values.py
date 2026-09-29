from __future__ import annotations

import dataclasses
import math

import pytest

from arena_wizard.domain.cards import Rarity
from arena_wizard.domain.scoring import ScoringConfig, Shrinkage, load_scoring_config
from arena_wizard.domain.sets import Format
from arena_wizard.domain.stats import CardCounts, PairCounts, Snapshot, SourceRef
from arena_wizard.engine.values import (
    FormatMeans,
    card_value,
    estimate_prior_games,
    format_means,
    pair_value,
    shrink,
    spell_rarities,
)
from tests.unit.test_lands import card, land

C, UNC, RARE, MYTHIC = Rarity.COMMON, Rarity.UNCOMMON, Rarity.RARE, Rarity.MYTHIC
SOURCE = SourceRef("made-up", None, None, None, 0)


def _config(prior: float = 100, iwd_prior: float = 50, pair_prior: float = 100) -> ScoringConfig:
    base = load_scoring_config(Format.BO1_SEALED)
    return dataclasses.replace(
        base,
        shrinkage=Shrinkage(prior, iwd_prior, pair_prior),
        weights=dataclasses.replace(base.weights, iwd=0.5),
    )


def _snapshot(cards: dict[str, CardCounts], pairs: dict[str, PairCounts] | None = None) -> Snapshot:
    return Snapshot("TST", SOURCE, cards, pairs or {})


MEANS = FormatMeans(gih=0.55, gih_by_rarity={C: 0.5}, gns_by_rarity={C: 0.45}, iwd=0.1, pair=0.5)


def test_shrinkage_adds_prior_pseudo_games() -> None:
    assert shrink(6, 10, 0.5, 10) == pytest.approx(0.55)
    assert shrink(6, 10, 0.5, 0) == pytest.approx(0.6)


def test_format_means_are_games_weighted_by_rarity_and_ignore_unknown_names() -> None:
    snapshot = _snapshot(
        {
            "Common": CardCounts(games_gih=100, wins_gih=60, games_gns=50, wins_gns=20),
            "Rare": CardCounts(games_gih=50, wins_gih=30, games_gns=30, wins_gns=10),
            "Unlisted": CardCounts(games_gih=1000, wins_gih=0, games_gns=1000, wins_gns=0),
        },
        {"WU": PairCounts(games=10, wins=6), "BG": PairCounts(games=30, wins=12)},
    )
    means = format_means(snapshot, {"Common": C, "Rare": RARE})
    assert means is not None
    assert means.gih == pytest.approx(90 / 150)
    assert means.gih_by_rarity == pytest.approx({C: 0.6, RARE: 0.6})
    assert means.gns_by_rarity == pytest.approx({C: 0.4, RARE: 1 / 3})
    assert means.iwd == pytest.approx(0.6 - 30 / 80)
    assert means.pair == pytest.approx(18 / 40)


def test_a_rarity_with_no_games_takes_the_format_mean() -> None:
    snapshot = _snapshot(
        {
            "Common": CardCounts(games_gih=100, wins_gih=60, games_gns=50, wins_gns=20),
            "Mythic": CardCounts(),
        }
    )
    means = format_means(snapshot, {"Common": C, "Mythic": MYTHIC})
    assert means is not None
    assert means.gih_by_rarity[MYTHIC] == pytest.approx(0.6)
    assert means.gns_by_rarity[MYTHIC] == pytest.approx(0.4)
    assert means.pair is None


def test_a_rarity_that_won_nothing_keeps_a_mean_of_zero() -> None:
    snapshot = _snapshot(
        {
            "Common": CardCounts(games_gih=100, wins_gih=60, games_gns=50, wins_gns=20),
            "Mythic": CardCounts(games_gih=5, wins_gih=0, games_gns=5, wins_gns=0),
        }
    )
    means = format_means(snapshot, {"Common": C, "Mythic": MYTHIC})
    assert means is not None
    assert means.gih_by_rarity[MYTHIC] == 0.0
    assert means.gns_by_rarity[MYTHIC] == 0.0


def test_format_means_are_none_without_in_hand_games() -> None:
    assert format_means(_snapshot({}), {}) is None


def test_format_means_are_none_without_not_seen_games() -> None:
    snapshot = _snapshot({"Common": CardCounts(games_gih=10, wins_gih=5)})
    assert format_means(snapshot, {"Common": C}) is None


def test_without_any_data_a_card_is_worth_zero_and_says_so() -> None:
    value = card_value("Card", C, None, None, _config(prior=180), "made-up")
    assert (value.q, value.observed, value.used, value.prior_share, value.games) == (
        0.0,
        None,
        None,
        None,
        0,
    )
    assert value.source == "no data loaded"
    assert value.se == pytest.approx(100 * math.sqrt(0.25 / 180))


@pytest.mark.parametrize("counts", [None, CardCounts()])
def test_a_card_with_no_games_is_worth_its_raritys_average(counts: CardCounts | None) -> None:
    value = card_value("Card", C, counts, MEANS, _config(), "made-up")
    assert value.q == pytest.approx(100 * (0.5 - 0.55))
    assert (value.observed, value.used, value.prior_share, value.games) == (None, 0.5, 1.0, 0)
    assert value.source == "common average"
    assert value.se == pytest.approx(100 * math.sqrt(0.25 / 100))


def test_a_card_with_games_is_shrunk_toward_its_rarity_and_credited_for_iwd() -> None:
    counts = CardCounts(games_gih=100, wins_gih=70, games_gns=50, wins_gns=20)
    value = card_value("Card", C, counts, MEANS, _config(), "made-up")
    # used = (70 + 0.5 * 100) / 200 = 0.6; gns used = (20 + 0.45 * 50) / 100 = 0.425
    # q = 100 * (0.6 - 0.55) + 0.5 * 100 * ((0.6 - 0.425) - (0.5 - 0.45)) = 5 + 6.25
    assert value.q == pytest.approx(11.25)
    assert value.observed == pytest.approx(0.7)
    assert value.used == pytest.approx(0.6)
    assert value.prior_share == pytest.approx(0.5)
    assert value.games == 100
    assert value.source == "made-up"
    assert value.se == pytest.approx(100 * math.sqrt(0.6 * 0.4 / 200))


def test_a_rarity_missing_from_the_means_falls_back_to_the_format_mean() -> None:
    counts = CardCounts(games_gih=100, wins_gih=70, games_gns=50, wins_gns=20)
    value = card_value("Card", RARE, counts, MEANS, _config(), "made-up")
    # used = (70 + 0.55 * 100) / 200 = 0.625; gns prior = 0.625 - 0.1 = 0.525
    # gns used = (20 + 0.525 * 50) / 100 = 0.4625; rarity IWD = 0.55 - 0.525 = 0.025
    expected = 100 * (0.625 - 0.55) + 0.5 * 100 * ((0.625 - 0.4625) - 0.025)
    assert value.q == pytest.approx(expected)


@pytest.mark.parametrize(
    ("counts", "means"),
    [
        (PairCounts(10, 6), None),
        (PairCounts(10, 6), dataclasses.replace(MEANS, pair=None)),
        (None, MEANS),
        (PairCounts(0, 0), MEANS),
    ],
)
def test_a_pair_without_games_scores_zero_with_no_rates(
    counts: PairCounts | None, means: FormatMeans | None
) -> None:
    assert pair_value("WU", counts, means, _config()) == pair_value("WU", None, None, _config())
    value = pair_value("WU", counts, means, _config())
    assert (value.points, value.observed, value.used, value.prior_share, value.games) == (
        0.0,
        None,
        None,
        None,
        0,
    )


def test_a_pair_with_games_is_shrunk_toward_the_pair_mean() -> None:
    value = pair_value("WU", PairCounts(games=100, wins=60), MEANS, _config())
    assert value.used == pytest.approx(0.55)
    assert value.points == pytest.approx(5.0)
    assert value.observed == pytest.approx(0.6)
    assert value.prior_share == pytest.approx(0.5)
    assert value.games == 100


def test_the_prior_size_matches_the_true_spread_of_win_rates() -> None:
    counts = [CardCounts(games_gih=1000, wins_gih=w) for w in (400, 500, 600)]
    observed_var = 0.01  # sample variance of 0.4, 0.5, 0.6
    sampling_var = (0.24 + 0.25 + 0.24) / 1000 / 3
    expected = (0.24 + 0.25 + 0.24) / 3 / (observed_var - sampling_var)
    assert estimate_prior_games(counts) == pytest.approx(expected)


def test_cards_under_the_game_floor_are_left_out_of_the_prior_estimate() -> None:
    counts = [CardCounts(games_gih=1000, wins_gih=w) for w in (400, 500, 600)]
    thin = CardCounts(games_gih=199, wins_gih=199)
    assert estimate_prior_games([*counts, thin]) == estimate_prior_games(counts)
    assert estimate_prior_games([*counts[:2], thin]) is None


def test_no_true_spread_gives_no_prior_estimate() -> None:
    assert estimate_prior_games([CardCounts(games_gih=1000, wins_gih=500)] * 3) is None


def test_spell_rarities_leave_out_lands() -> None:
    cards = [
        card("Spell", "{W}", 1.0, rarity=MYTHIC),
        land("Dual", ("W", "B")),
        card("Plains", type_line="Basic Land — Plains", produced=("W",)),
    ]
    assert spell_rarities(cards) == {"Spell": MYTHIC}
