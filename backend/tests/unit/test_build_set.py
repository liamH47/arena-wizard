from __future__ import annotations

import datetime as dt
from collections import Counter
from fractions import Fraction

import pytest

from arena_wizard.eval.build_set import choose_split_day, select_sample
from arena_wizard.eval.records import BuildRecord, PoolRecord


def _record(draft_id: str, day: int, colors: str) -> PoolRecord:
    return PoolRecord(
        draft_id=draft_id,
        first_day=dt.date(2026, 4, day),
        pool={"Alpha": 1},
        builds=(BuildRecord(0, colors, "", {"Alpha": 1}, 3, 2),),
        win_rate_bucket=0.5,
        games_bucket=10,
    )


def test_the_split_day_is_where_sixty_percent_of_games_have_been_played() -> None:
    days = {dt.date(2026, 4, d): n for d, n in [(21, 30), (22, 25), (23, 25), (24, 20)]}
    # Running totals 30, 55, 80: the 23rd is the first day at or past 60 of 100.
    assert choose_split_day(days) == dt.date(2026, 4, 23)
    assert choose_split_day(days, share=Fraction(3, 10)) == dt.date(2026, 4, 21)


def test_exactly_sixty_percent_counts_where_floating_point_would_not() -> None:
    # 0.6 * 100 is 60.00000000000001 in floating point; 60 games of 100 must reach it.
    days = {dt.date(2026, 4, 21): 60, dt.date(2026, 4, 22): 40}
    assert choose_split_day(days) == dt.date(2026, 4, 21)


def test_a_split_without_games_is_an_error() -> None:
    with pytest.raises(ValueError, match="no games"):
        choose_split_day({dt.date(2026, 4, 21): 0})


def _population() -> dict[str, PoolRecord]:
    records = [_record(f"early{i}", 21, "WB") for i in range(5)]
    records += [_record(f"wb{i}", 23, "WB") for i in range(60)]
    records += [_record(f"ur{i}", 23, "UR") for i in range(30)]
    records += [_record(f"bg{i}", 24, "BG") for i in range(10)]
    return {r.draft_id: r for r in records}


def test_the_sample_excludes_pools_that_started_on_or_before_the_split() -> None:
    sample = select_sample(_population(), dt.date(2026, 4, 21), 50)
    assert not any(r.draft_id.startswith("early") for r in sample)


def test_the_sample_is_stratified_in_proportion_to_first_deck_colors() -> None:
    sample = select_sample(_population(), dt.date(2026, 4, 21), 50)
    assert Counter(r.first_build.main_colors for r in sample) == {"WB": 30, "UR": 15, "BG": 5}


def test_rounding_hands_leftover_slots_to_the_largest_remainders() -> None:
    sample = select_sample(_population(), dt.date(2026, 4, 21), 7)
    assert Counter(r.first_build.main_colors for r in sample) == {"WB": 4, "UR": 2, "BG": 1}


def test_the_sample_is_reproducible_and_independent_of_input_order() -> None:
    population = _population()
    reversed_population = dict(reversed(list(population.items())))
    first = select_sample(population, dt.date(2026, 4, 21), 20)
    assert first == select_sample(reversed_population, dt.date(2026, 4, 21), 20)


def test_a_sample_larger_than_the_eligible_pools_takes_them_all() -> None:
    assert len(select_sample(_population(), dt.date(2026, 4, 23), 500)) == 10
    assert select_sample(_population(), dt.date(2026, 4, 30), 10) == ()
