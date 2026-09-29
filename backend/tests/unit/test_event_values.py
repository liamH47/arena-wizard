"""The event-mode value chain: grades, then draft data, then Arena Direct (decision 0007).

Every number is made up. Snapshots are built so the format mean is exactly 0.5.
"""

from __future__ import annotations

import math

import pytest

from arena_wizard.domain.cards import Rarity
from arena_wizard.domain.decks import LayerShare, ValueBasis
from arena_wizard.domain.stats import CardCounts, Snapshot, SourceRef
from arena_wizard.engine.event_values import DataLayer, data_layer, event_value
from arena_wizard.engine.grades import GradeScores
from arena_wizard.engine.values import iwd_points, shrink
from tests.engine_fixture import CONFIG, card

C, R = Rarity.COMMON, Rarity.RARE
EVENT = CONFIG.event
PLAIN = card("Plain", "{1}{W}")
KILL = card("Kill", "{1}{B}", kind="Instant", text="Destroy target creature.", rarity=R)
BENCH = card("Bench", "{2}{W}")
OTHER = card("Other", "{2}{U}")
RARITY = {"Plain": C, "Kill": R, "Bench": C, "Other": C}
SOURCE = SourceRef("made-up", None, None, None, 0)


def _grades(z: dict[str, float], rarity_z: dict[Rarity, float] | None = None) -> GradeScores:
    return GradeScores(
        z=z,
        rarity_z=rarity_z if rarity_z is not None else {},
        raw={name: (("Reviewer", "B"),) for name in z},
        labels=("Reviewer",),
    )


def _layer(cards: dict[str, CardCounts], *, proxy: bool, name: str = "layer") -> DataLayer:
    layer = data_layer(name, Snapshot("TST", SOURCE, cards, {}), RARITY, proxy)
    assert layer is not None
    return layer


def _even(n: int = 1000, *, gns: bool = False) -> dict[str, CardCounts]:
    """Plain wins 60%, Bench 40%: both commons, so the format and common means are 0.5."""
    extra = {"games_gns": n, "wins_gns": n // 2} if gns else {}
    return {
        "Plain": CardCounts(games_gih=n, wins_gih=n * 6 // 10, **extra),
        "Bench": CardCounts(games_gih=n, wins_gih=n * 4 // 10, **extra),
    }


def test_a_missing_or_empty_snapshot_is_no_layer() -> None:
    assert data_layer("x", None, RARITY, False) is None
    empty = Snapshot("TST", SOURCE, {"Plain": CardCounts()}, {})
    assert data_layer("x", empty, RARITY, False) is None


def test_without_grades_or_data_nothing_values_a_card() -> None:
    with pytest.raises(ValueError, match="grades or at least one data layer"):
        event_value(PLAIN, None, None, None, CONFIG)


def test_a_graded_card_alone_is_exactly_its_grade_value_with_the_grade_error() -> None:
    value = event_value(PLAIN, _grades({"Plain": 1.0}), None, None, CONFIG)
    assert value.q == pytest.approx(EVENT.center + EVENT.slope * 1.0)
    assert value.se == pytest.approx(EVENT.sigma)
    assert value.basis is ValueBasis.GRADES
    assert value.source == "draft grades"
    assert value.layers == (LayerShare("draft grades", 1.0),)
    assert value.grades == (("Reviewer", "B"),)
    assert value.observed is None and value.used is None and value.games == 0
    assert value.prior_share == 1.0


def test_sealed_adds_removal_and_rarity_on_top_of_a_draft_grade() -> None:
    value = event_value(KILL, _grades({"Kill": 0.0}), None, None, CONFIG)
    assert value.q == pytest.approx(EVENT.center + EVENT.removal_bonus + EVENT.rare_bonus)


def test_an_a_plus_card_is_worth_more_than_an_f_card() -> None:
    grades = _grades({"Plain": 2.0, "Bench": -2.0})
    top = event_value(PLAIN, grades, None, None, CONFIG)
    bottom = event_value(BENCH, grades, None, None, CONFIG)
    assert top.q > bottom.q


def test_an_ungraded_card_sits_at_its_raritys_mean_grade_one_spread_wide() -> None:
    grades = _grades({"Plain": 1.0}, {C: 0.4})
    value = event_value(OTHER, grades, None, None, CONFIG)
    assert value.q == pytest.approx(EVENT.center + EVENT.slope * 0.4)
    assert value.se == pytest.approx(math.sqrt(EVENT.sigma**2 + EVENT.slope**2))
    assert value.basis is ValueBasis.RARITY_GRADE
    assert value.source == "common average grade"
    assert value.grades == ()


def test_an_ungraded_card_of_an_ungraded_rarity_sits_at_the_average_grade() -> None:
    value = event_value(KILL, _grades({"Plain": 1.0}, {C: 0.4}), None, None, CONFIG)
    assert value.q == pytest.approx(EVENT.center + EVENT.removal_bonus + EVENT.rare_bonus)


def test_without_grades_an_unseen_card_takes_its_raritys_average_in_the_data() -> None:
    layer = _layer(_even(), proxy=False)
    value = event_value(OTHER, None, None, layer, CONFIG)
    assert value.basis is ValueBasis.RARITY
    assert value.q == pytest.approx(0.0)
    assert value.se == pytest.approx(100 * math.sqrt(0.25 / CONFIG.shrinkage.prior_games))
    assert value.source == "common average"


def test_a_direct_reading_combines_with_the_grade_by_inverse_variance() -> None:
    layer = _layer(_even(), proxy=False, name="Arena Direct")
    value = event_value(PLAIN, _grades({"Plain": 0.0}), None, layer, CONFIG)
    prior_mean, prior_var = EVENT.center, EVENT.sigma**2
    reading, reading_var = 10.0, 100**2 * 0.25 / 1000
    variance = 1 / (1 / prior_var + 1 / reading_var)
    assert value.q == pytest.approx(variance * (prior_mean / prior_var + reading / reading_var))
    assert value.se == pytest.approx(math.sqrt(variance))
    assert value.basis is ValueBasis.WIN_RATES
    assert value.observed == pytest.approx(0.6) and value.games == 1000
    assert value.source == "Arena Direct; improvement when drawn not available"
    assert [s.name for s in value.layers] == ["draft grades", "Arena Direct"]
    assert sum(s.share for s in value.layers) == pytest.approx(1.0)
    assert value.prior_share == pytest.approx(variance / prior_var)


def test_a_direct_reading_gets_no_sealed_bonus_but_a_proxy_reading_does() -> None:
    cards = {"Kill": CardCounts(games_gih=1000, wins_gih=600), **_even()}
    grades = _grades({"Kill": 0.0})
    prior_mean, prior_var = EVENT.center + 2.0, EVENT.sigma**2

    def posterior(reading: float, reading_var: float) -> float:
        variance = 1 / (1 / prior_var + 1 / reading_var)
        return variance * (prior_mean / prior_var + reading / reading_var)

    # Kill's rarity mean is its own 0.6, so the format mean is (600+600+400)/3000.
    m = 1600 / 3000
    sampling = 100**2 * m * (1 - m) / 1000
    direct = event_value(KILL, grades, None, _layer(cards, proxy=False), CONFIG)
    assert direct.q == pytest.approx(posterior(100 * (0.6 - m), sampling))
    proxy = event_value(KILL, grades, _layer(cards, proxy=True), None, CONFIG)
    assert proxy.basis is ValueBasis.DRAFT_PROXY
    assert proxy.q == pytest.approx(
        posterior(
            EVENT.proxy_slope * 100 * (0.6 - m) + 2.0,
            EVENT.proxy_sigma**2 + EVENT.proxy_slope**2 * sampling,
        )
    )


def test_a_thin_arena_direct_sample_tightens_draft_data_instead_of_replacing_it() -> None:
    grades = _grades({"Plain": 0.0, "Bench": 0.0})
    draft = _layer(_even(5000), proxy=True, name="draft data")
    thin = {
        "Plain": CardCounts(games_gih=20, wins_gih=6),
        "Bench": CardCounts(games_gih=20, wins_gih=14),
    }
    direct = _layer(thin, proxy=False, name="Arena Direct")
    draft_only = event_value(PLAIN, grades, draft, None, CONFIG).q
    chained = event_value(PLAIN, grades, draft, direct, CONFIG)
    replaced = event_value(PLAIN, grades, None, direct, CONFIG).q
    assert abs(chained.q - draft_only) < abs(replaced - draft_only)
    assert [s.name for s in chained.layers] == ["draft grades", "draft data", "Arena Direct"]
    assert sum(s.share for s in chained.layers) == pytest.approx(1.0)
    assert chained.basis is ValueBasis.WIN_RATES


def test_with_many_games_the_value_converges_to_the_observed_reading() -> None:
    layer = _layer(_even(1_000_000), proxy=False)
    value = event_value(PLAIN, _grades({"Plain": -2.0}), None, layer, CONFIG)
    assert value.q == pytest.approx(10.0, abs=0.01)
    assert value.prior_share is not None and value.prior_share < 1e-3


def test_a_card_with_no_games_in_a_layer_is_not_read_from_it() -> None:
    cards = {**_even(), "Other": CardCounts(games_gih=0)}
    value = event_value(OTHER, _grades({"Other": 1.0}), None, _layer(cards, proxy=False), CONFIG)
    assert value.basis is ValueBasis.GRADES
    assert value.q == pytest.approx(EVENT.center + EVENT.slope)


def _iwd_expected(layer: DataLayer, name: str) -> float:
    counts = layer.snapshot.cards[name]
    prior = layer.means.gih_by_rarity[C]
    used = shrink(counts.wins_gih, counts.games_gih, prior, CONFIG.shrinkage.prior_games)
    return CONFIG.weights.iwd * iwd_points(counts, C, used, layer.means, CONFIG)


def test_improvement_when_drawn_comes_from_the_top_layer_with_not_seen_games() -> None:
    cards = _even(gns=True)
    cards["Plain"] = CardCounts(games_gih=1000, wins_gih=600, games_gns=1000, wins_gns=400)
    direct = _layer(cards, proxy=False, name="Arena Direct")
    grades = _grades({"Plain": 0.0})
    with_iwd = event_value(PLAIN, grades, None, direct, CONFIG)
    without = event_value(PLAIN, grades, None, _layer(_even(), proxy=False), CONFIG)
    assert with_iwd.source == "Arena Direct"
    assert with_iwd.q - without.q == pytest.approx(_iwd_expected(direct, "Plain"))
    assert _iwd_expected(direct, "Plain") != 0


def test_a_proxy_layers_improvement_is_scaled_to_sealed() -> None:
    cards = _even(gns=True)
    cards["Plain"] = CardCounts(games_gih=1000, wins_gih=600, games_gns=1000, wins_gns=400)
    draft = _layer(cards, proxy=True, name="draft data")
    direct = _layer(_even(), proxy=False, name="Arena Direct")  # no not-seen columns
    grades = _grades({"Plain": 0.0})
    with_iwd = event_value(PLAIN, grades, draft, direct, CONFIG)
    plain_draft = _layer(_even(), proxy=True, name="draft data")
    without = event_value(PLAIN, grades, plain_draft, direct, CONFIG)
    assert with_iwd.source == "Arena Direct"
    assert with_iwd.q - without.q == pytest.approx(
        EVENT.proxy_slope * _iwd_expected(draft, "Plain")
    )


def test_a_card_never_unseen_in_the_top_layer_takes_improvement_from_below() -> None:
    top = _even(gns=True)
    top["Plain"] = CardCounts(games_gih=1000, wins_gih=600)  # in hand, never unseen
    below = _even(gns=True)
    below["Plain"] = CardCounts(games_gih=1000, wins_gih=600, games_gns=1000, wins_gns=400)
    grades = _grades({"Plain": 0.0})
    value = event_value(
        PLAIN,
        grades,
        _layer(below, proxy=True, name="draft data"),
        _layer(top, proxy=False, name="Arena Direct"),
        CONFIG,
    )
    assert value.source == "Arena Direct"


def test_a_card_missing_from_the_top_layer_uses_the_layer_below() -> None:
    top = {"Bench": CardCounts(games_gih=1000, wins_gih=400)}
    value = event_value(
        PLAIN,
        _grades({"Plain": 0.0}),
        _layer(_even(), proxy=True, name="draft data"),
        _layer(top, proxy=False, name="Arena Direct"),
        CONFIG,
    )
    assert value.basis is ValueBasis.DRAFT_PROXY
    assert value.source == "draft data; improvement when drawn not available"
