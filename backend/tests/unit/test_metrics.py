from __future__ import annotations

import math
import random

import pytest

from arena_wizard.eval.metrics import (
    Binomial,
    Group,
    Observation,
    Scored,
    auc,
    auc_margin,
    jaccard,
    logistic_fit,
    logistic_slope,
    mean,
    mean_difference,
    paired_rate_difference,
    rate_difference,
    standardize,
    weighted_share,
    wilson,
)


def test_wilson_matches_the_textbook_interval() -> None:
    e = wilson(8, 10)
    assert e.value == 0.8 and e.n == 10
    assert e.low == pytest.approx(0.4902, abs=1e-4)
    assert e.high == pytest.approx(0.9433, abs=1e-4)


def test_wilson_without_trials_is_unknown_not_zero() -> None:
    e = wilson(0, 0)
    assert (e.value, e.low, e.high, e.n) == (None, None, None, 0)


def test_weighted_share_weights_each_hit() -> None:
    assert weighted_share([True, False, True], [1.0, 2.0, 1.0]) == 0.5
    assert weighted_share([], []) is None


def test_rate_difference_pools_games_and_brackets_the_point() -> None:
    rng = random.Random(0)
    first = [Group(6, 10), Group(7, 10), Group(0, 0)]
    second = [Group(4, 10), Group(5, 10)]
    e = rate_difference(first, second, rng, resamples=200)
    assert e.value == pytest.approx(0.65 - 0.45)
    assert e.value is not None and e.low is not None and e.high is not None
    assert e.low <= e.value <= e.high
    assert e.n == 4


def test_rate_difference_is_unknown_when_a_side_has_no_games() -> None:
    e = rate_difference([Group(1, 2)], [Group(0, 0)], random.Random(0))
    assert e.value is None and e.n == 1


def test_seeded_resampling_is_reproducible() -> None:
    args = ([Group(6, 10), Group(2, 9)], [Group(4, 10), Group(5, 7)])
    a = rate_difference(*args, random.Random(7), resamples=100)
    b = rate_difference(*args, random.Random(7), resamples=100)
    assert a == b


def test_mean_difference_and_its_empty_case() -> None:
    e = mean_difference([1.0, 3.0], [1.0], random.Random(0), resamples=50)
    assert e.value == 1.0 and e.n == 3
    assert mean_difference([], [1.0], random.Random(0)).value is None


def test_mean_with_zero_one_and_many_values() -> None:
    assert mean([]).value is None
    single = mean([2.0])
    assert single.value == 2.0 and single.low is None
    many = mean([1.0, 2.0, 3.0])
    assert many.value == 2.0 and many.low is not None and many.low < 2.0 < (many.high or 0)


def test_logistic_slope_recovers_a_known_positive_effect() -> None:
    points = [
        Binomial(x, 1000, round(1000 / (1 + math.exp(-(0.2 + 0.5 * x))))) for x in (-2, -1, 0, 1, 2)
    ]
    slope = logistic_slope(points)
    assert slope == pytest.approx(0.5, abs=0.01)


def test_logistic_slope_needs_two_distinct_values() -> None:
    assert logistic_slope([Binomial(1.0, 10, 5), Binomial(1.0, 5, 2)]) is None
    assert logistic_slope([Binomial(1.0, 0, 0), Binomial(2.0, 0, 0)]) is None


def test_logistic_slope_stops_when_the_fit_degenerates() -> None:
    # Perfect separation drives the curvature to zero; the fit must stop, not divide by it.
    slope = logistic_slope([Binomial(0.0, 10, 0), Binomial(1.0, 10, 10)], iterations=200)
    assert slope is not None and slope > 5


def test_auc_counts_ties_as_half_and_needs_both_outcomes() -> None:
    assert auc([Binomial(0.0, 1, 0), Binomial(1.0, 1, 1)]) == 1.0
    assert auc([Binomial(1.0, 2, 1)]) == 0.5
    assert auc([Binomial(1.0, 2, 2)]) is None


def test_standardize_and_constant_values() -> None:
    assert standardize([1.0, 3.0]) == [-1.0, 1.0]
    assert standardize([2.0, 2.0]) == [0.0, 0.0]


def test_multiset_jaccard() -> None:
    assert jaccard({"a": 2, "b": 1}, {"a": 1, "c": 1}) == pytest.approx(1 / 4)
    assert jaccard({}, {}) is None


def _sigmoid(z: float) -> float:
    return 1 / (1 + math.exp(-z))


def test_logistic_fit_recovers_two_known_effects() -> None:
    rows = [
        Observation((x, s), 4000, round(4000 * _sigmoid(-0.3 + 0.4 * x - 0.8 * s)))
        for x in (-1.0, 0.0, 1.0)
        for s in (0.0, 1.0)
    ]
    fit = logistic_fit(rows)
    assert fit is not None
    assert fit == pytest.approx((-0.3, 0.4, -0.8), abs=0.01)


def test_logistic_fit_without_games_is_unknown() -> None:
    assert logistic_fit([]) is None
    assert logistic_fit([Observation((1.0,), 0, 0)]) is None


def test_logistic_fit_of_a_covariate_that_never_varies_is_singular() -> None:
    # Two identical columns (the intercept and a constant 1.0) cannot be told apart.
    assert logistic_fit([Observation((1.0,), 10, 4), Observation((1.0,), 10, 6)]) is None


def test_paired_rate_difference_resamples_pairs_jointly() -> None:
    pairs = [
        (Group(6, 10), Group(4, 10)),
        (Group(3, 5), Group(1, 5)),
        (Group(2, 2), Group(0, 0)),  # dropped: one side has no games
    ]
    e = paired_rate_difference(pairs, random.Random(3), resamples=200)
    assert e.value == pytest.approx(9 / 15 - 5 / 15)
    assert e.n == 2
    assert e.value is not None and e.low is not None and e.high is not None
    assert e.low <= e.value <= e.high
    assert e == paired_rate_difference(pairs, random.Random(3), resamples=200)


def test_paired_rate_difference_without_usable_pairs_is_unknown() -> None:
    e = paired_rate_difference([(Group(1, 1), Group(0, 0))], random.Random(0))
    assert (e.value, e.low, e.high, e.n) == (None, None, None, 0)


def test_auc_margin_is_the_engine_auc_minus_the_baseline_auc() -> None:
    # The engine ranks the win above the loss; the baseline ranks them the other way.
    clusters = [
        [Scored(engine=2.0, baseline=0.0, games=1, wins=1)],
        [Scored(engine=1.0, baseline=1.0, games=1, wins=0)],
        [],
    ]
    e = auc_margin(clusters, random.Random(0), resamples=100)
    assert e.value == 1.0 and e.n == 2
    assert e.low is not None and e.high is not None and e.low <= 1.0 <= e.high


def test_auc_margin_without_wins_and_losses_is_unknown() -> None:
    e = auc_margin([[Scored(1.0, 1.0, 2, 2)]], random.Random(0))
    assert (e.value, e.low, e.high, e.n) == (None, None, None, 1)
