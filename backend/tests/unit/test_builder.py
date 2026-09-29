from __future__ import annotations

import dataclasses
import datetime as dt
import json
import os
import random
import subprocess
import sys
from pathlib import Path

import pytest

from arena_wizard.domain.cards import Card, Color, Rarity
from arena_wizard.domain.decks import ScoredDeck
from arena_wizard.domain.stats import CardCounts, PairCounts, Snapshot, SourceRef
from arena_wizard.engine import builder
from arena_wizard.engine.bombs import CuratedBomb
from arena_wizard.engine.builder import (
    BuildInputs,
    _gap_se,
    _splash_bound,
    build_decks,
    build_for_pair,
    pair_code,
    prepare_inputs,
    score_spells,
)
from arena_wizard.engine.mana import can_cast, castable_cost
from arena_wizard.engine.roles import Role, classify
from arena_wizard.engine.values import PairValue
from tests.engine_fixture import (
    CONFIG,
    B,
    G,
    R,
    U,
    W,
    card,
    dual,
    make_inputs,
    make_pool,
    no_pairs,
    removal,
    three_pair_pool,
)

BACKEND = Path(__file__).resolve().parents[2]


def _decks() -> tuple[ScoredDeck, ...]:
    pool, q = three_pair_pool()
    return build_decks(pool, make_inputs(pool, q)).decks


def _signature(decks: tuple[ScoredDeck, ...]) -> list[tuple[object, ...]]:
    return [
        (
            d.label,
            d.total,
            d.total_se,
            [(e.card.front_name, e.count) for e in d.spells],
            [(land.name, land.count) for land in d.lands],
            d.gap_to_next,
            d.gap_se,
        )
        for d in decks
    ]


def _wu_pool(*extra: tuple[Card, int]) -> list[tuple[Card, int]]:
    """Twenty-four white and blue spells: exactly one buildable pair."""
    spells: list[tuple[Card, int]] = []
    for color in "WU":
        for i in range(10):
            spells.append((card(f"{color} Body {i}", f"{{{i % 4}}}{{{color}}}"), 1))
        spells.append((removal(f"{color} Kill", f"{{2}}{{{color}}}"), 2))
    return spells + list(extra)


def test_every_deck_is_a_legal_forty_built_from_the_pool() -> None:
    pool, q = three_pair_pool()
    in_pool = {e.card.front_name: e.count for e in pool.entries}
    decks = build_decks(pool, make_inputs(pool, q)).decks
    assert len(decks) >= 3
    for deck in decks:
        assert deck.spell_count + deck.land_count == 40
        assert deck.land_count in (16, 17)
        main = [Color(c) for c in deck.colors]
        allowed = main + ([deck.splash] if deck.splash else [])
        for entry in deck.spells:
            assert entry.count <= in_pool[entry.card.front_name]
            cost = castable_cost(entry.card)
            assert can_cast(cost, allowed)
            assert can_cast(cost, main) or deck.splash is not None


def test_the_best_deck_is_first_and_totals_are_the_sum_of_their_terms() -> None:
    pool, q = three_pair_pool()
    inputs = make_inputs(pool, q)
    decks = build_decks(pool, inputs).decks
    assert [d.total for d in decks] == sorted((d.total for d in decks), reverse=True)
    for deck in decks:
        assert deck.total == pytest.approx(sum(t.contribution for t in deck.terms))
        assert [t.name for t in deck.terms][0] == "card_quality"
        assert deck.values == tuple(inputs.values[e.card.front_name] for e in deck.spells)


def test_each_deck_records_its_gap_to_the_next_with_a_standard_error() -> None:
    decks = _decks()
    for deck, nxt in zip(decks, decks[1:], strict=False):
        assert deck.gap_to_next == pytest.approx(deck.total - nxt.total)
        assert deck.gap_se is not None and deck.gap_se > 0
        assert deck.gap_to_next is not None
        assert deck.is_toss_up == (deck.gap_to_next < deck.gap_se)
    assert decks[-1].gap_to_next is None and decks[-1].gap_se is None
    assert not decks[-1].is_toss_up


def test_a_fourth_deck_is_kept_only_when_it_is_within_error_of_the_third() -> None:
    pool, q = three_pair_pool()
    uncertain = build_decks(pool, make_inputs(pool, q, se=5.0)).decks
    certain = build_decks(pool, make_inputs(pool, q, se=0.001)).decks
    assert len(uncertain) > 3
    assert len(certain) == 3
    assert [(d.label, d.total) for d in certain] == [(d.label, d.total) for d in uncertain[:3]]


def test_shuffling_the_pool_order_changes_nothing() -> None:
    pool, q = three_pair_pool()
    expected = _signature(build_decks(pool, make_inputs(pool, q)).decks)
    entries = list(pool.entries)
    random.Random(7).shuffle(entries)
    shuffled = dataclasses.replace(pool, entries=tuple(entries))
    assert _signature(build_decks(shuffled, make_inputs(shuffled, q)).decks) == expected


SCRIPT = """
import json
from arena_wizard.engine.builder import build_decks
from tests.engine_fixture import make_inputs, three_pair_pool
pool, q = three_pair_pool()
decks = build_decks(pool, make_inputs(pool, q)).decks
print(json.dumps([
    [d.label, repr(d.total), [[e.card.front_name, e.count] for e in d.spells],
     [[land.name, land.count] for land in d.lands]]
    for d in decks
]))
"""


def test_the_same_pool_builds_the_same_decks_under_different_hash_seeds() -> None:
    outputs = []
    for seed in ("1", "2"):
        env = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONPATH": str(BACKEND)}
        done = subprocess.run(
            [sys.executable, "-c", SCRIPT],
            cwd=BACKEND,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        )
        outputs.append(json.loads(done.stdout))
    assert outputs[0] == outputs[1]
    assert len(outputs[0]) >= 3


def test_a_pool_with_one_buildable_pair_returns_just_that_deck() -> None:
    pool = make_pool(_wu_pool())
    result = build_decks(pool, make_inputs(pool, {}))
    (deck,) = result.decks
    assert deck.label == "WU"
    assert deck.gap_to_next is None


def test_a_pool_too_thin_for_any_pair_builds_nothing() -> None:
    pool = make_pool([(card("W Lone", "{W}"), 5), (card("U Lone", "{U}"), 5)])
    assert build_decks(pool, make_inputs(pool, {})).decks == ()


def test_a_strong_single_pip_removal_spell_is_splashed_off_three_land_sources() -> None:
    pool = make_pool(_wu_pool((removal("R Bolt", "{R}"), 1)))
    decks = build_decks(pool, make_inputs(pool, {"R Bolt": 25.0})).decks
    splash = next(d for d in decks if d.splash is R)
    assert splash.label == "WU+r"
    assert dict(splash.sources)[R] == CONFIG.targets.splash_min_sources
    assert "R Bolt" in {e.card.front_name for e in splash.spells}


def test_a_splash_stops_at_three_cards_however_many_are_worth_it() -> None:
    bolts = [(removal(f"R Bolt {i}", "{R}"), 1) for i in range(5)]
    pool = make_pool(_wu_pool(*bolts))
    q = {f"R Bolt {i}": 25.0 for i in range(5)}
    splash = next(d for d in build_decks(pool, make_inputs(pool, q)).decks if d.splash is R)
    assert sum(e.count for e in splash.spells if R in e.card.colors) == (
        CONFIG.targets.splash_max_cards
    )


@pytest.mark.parametrize(("steps", "labels"), [(0, ["WU"]), (1, ["WU+r", "WU"])])
def test_the_climb_stops_at_its_step_limit(
    monkeypatch: pytest.MonkeyPatch, steps: int, labels: list[str]
) -> None:
    # The splash card only enters by a swap, so with no steps there is no splash deck.
    monkeypatch.setattr(builder, "MAX_STEPS", steps)
    pool = make_pool(_wu_pool((removal("R Bolt", "{R}"), 1)))
    decks = build_decks(pool, make_inputs(pool, {"R Bolt": 25.0})).decks
    assert [d.label for d in decks] == labels


def test_a_splash_no_card_survives_into_is_not_offered() -> None:
    pool = make_pool(_wu_pool((removal("R Bolt", "{R}"), 1)))
    decks = build_decks(pool, make_inputs(pool, {"R Bolt": -5.0})).decks
    assert [d.label for d in decks] == ["WU"]


def test_cards_that_are_not_splashable_never_start_a_splash() -> None:
    # A double pip, and a cheap spell that is not removal, are not splash cards.
    extra = ((card("R Twin", "{R}{R}"), 1), (card("R Cub", "{1}{R}"), 1))
    pool = make_pool(_wu_pool(*extra))
    decks = build_decks(pool, make_inputs(pool, {"R Twin": 40.0, "R Cub": 40.0})).decks
    assert [d.label for d in decks] == ["WU"]


def test_a_splash_with_no_land_slot_left_for_its_sources_is_dropped() -> None:
    with_duals = make_pool(_wu_pool((removal("R Bolt", "{R}"), 1), (dual("WU Gate", "WU"), 17)))
    decks = build_decks(with_duals, make_inputs(with_duals, {"R Bolt": 25.0})).decks
    assert [d.label for d in decks] == ["WU"]
    assert decks[0].lands[0].name == "WU Gate"
    # The same pool without the duals does splash, so the duals are why it was dropped.
    without = make_pool(_wu_pool((removal("R Bolt", "{R}"), 1)))
    labels = [d.label for d in build_decks(without, make_inputs(without, {"R Bolt": 25.0})).decks]
    assert "WU+r" in labels


def test_the_splash_bound_is_never_below_what_a_splash_actually_gained() -> None:
    pool, q = three_pair_pool()
    inputs = make_inputs(pool, q)
    decks = build_decks(pool, inputs).decks
    bases = {d.colors: d for d in decks if d.splash is None}
    checked = 0
    for deck in decks:
        if deck.splash is not None and deck.colors in bases:
            base = bases[deck.colors]
            gained = deck.total - base.total
            assert gained <= _splash_bound(base, pool, deck.splash, inputs) + 1e-9
            checked += 1
    assert checked >= 1


def test_a_splash_whose_bound_cannot_reach_the_third_deck_is_never_built() -> None:
    pool, q = three_pair_pool()
    inputs = make_inputs(pool, q)
    labels = [d.label for d in build_decks(pool, inputs).decks]
    assert not any(label.endswith("+g") for label in labels)
    wu = build_for_pair(pool, inputs, "WU")
    assert wu is not None
    assert _splash_bound(wu, pool, G, inputs) < 0


def test_build_for_pair_matches_the_unsplashed_deck_and_refuses_an_unbuildable_pair() -> None:
    pool, q = three_pair_pool()
    inputs = make_inputs(pool, q)
    wu = build_for_pair(pool, inputs, "WU")
    assert wu is not None and wu.label == "WU"
    listed = next(d for d in build_decks(pool, inputs).decks if d.label == "WU")
    assert _signature((wu,))[0][:5] == _signature((listed,))[0][:5]
    assert build_for_pair(pool, inputs, "RG") is None


def test_score_spells_scores_a_given_list_with_lands_chosen_for_it() -> None:
    pool, q = three_pair_pool()
    inputs = make_inputs(pool, q)
    chosen = [(e.card, e.count) for e in pool.entries if set(e.card.colors) <= {W, U}]
    chosen = [(c, n) for c, n in chosen if Role.LAND not in classify(c)][:23]
    deck = score_spells(pool, chosen, "WU", None, inputs)
    assert deck.label == "WU"
    assert deck.spell_count == sum(n for _, n in chosen)
    assert deck.spell_count + deck.land_count == 40
    assert deck.total == pytest.approx(sum(t.contribution for t in deck.terms))
    splashed = score_spells(pool, [*chosen[:22], (removal("R Bolt", "{R}"), 1)], "WU", R, inputs)
    assert splashed.label == "WU+r"
    assert next(t for t in splashed.terms if t.name == "splash").raw == -1


def test_pair_code_orders_colors_the_way_17lands_writes_them() -> None:
    assert pair_code([G, B]) == "BG"
    assert pair_code([U, W, W]) == "WU"


def _gap_inputs(pair_strength: float) -> tuple[BuildInputs, ScoredDeck, ScoredDeck]:
    pool, q = three_pair_pool()
    config = dataclasses.replace(
        CONFIG, weights=dataclasses.replace(CONFIG.weights, pair_strength=pair_strength)
    )
    pairs = no_pairs()
    pairs["WU"] = PairValue("WU", 2.0, 0.57, 0.56, 0.3, 700)
    inputs = make_inputs(pool, q, pairs=pairs, config=config)
    wu = build_for_pair(pool, inputs, "WU")
    wb = build_for_pair(pool, inputs, "WB")
    assert wu is not None and wb is not None
    return inputs, wu, wb


def test_identical_decks_have_no_gap_error() -> None:
    inputs, wu, _ = _gap_inputs(1.0)
    assert _gap_se(wu, wu, inputs) == 0.0


def test_two_copies_of_a_card_count_four_times_the_variance_of_one() -> None:
    inputs, wu, _ = _gap_inputs(0.0)
    entry = next(e for e in wu.spells if e.count == 1)
    two = dataclasses.replace(
        wu, spells=tuple(dataclasses.replace(e, count=2) if e is entry else e for e in wu.spells)
    )
    three = dataclasses.replace(
        wu, spells=tuple(dataclasses.replace(e, count=3) if e is entry else e for e in wu.spells)
    )
    se = inputs.values[entry.card.front_name].se
    assert _gap_se(wu, two, inputs) == pytest.approx(se)
    assert _gap_se(wu, three, inputs) == pytest.approx(2 * se)


def test_the_pair_term_adds_error_only_when_the_colors_differ_and_the_pair_has_games() -> None:
    weighted, wu, wb = _gap_inputs(1.0)
    unweighted, wu0, wb0 = _gap_inputs(0.0)
    pair_se = 100 * (0.56 * 0.44 / (700 + CONFIG.shrinkage.pair_prior_games)) ** 0.5
    assert _gap_se(wu, wb, weighted) ** 2 == pytest.approx(
        _gap_se(wu0, wb0, unweighted) ** 2 + pair_se**2
    )
    assert wu.total_se**2 == pytest.approx(wu0.total_se**2 + pair_se**2)


def _snapshot() -> Snapshot:
    source = SourceRef("made-up games", dt.date(2026, 5, 1), dt.date(2026, 5, 30), None, 900)
    cards = {"W Creature 0": CardCounts(300, 180, 200, 100, 500, 280)}
    for i in range(60):
        cards[f"Filler {i}"] = CardCounts(200, 100 + i, 150, 80, 350, 180 + i)
    return Snapshot("TST", source, cards, {"WU": PairCounts(400, 230), "WB": PairCounts(300, 150)})


def test_without_statistics_every_value_says_no_data_and_nothing_is_a_bomb() -> None:
    pool, _ = three_pair_pool()
    inputs = prepare_inputs(pool, None, {}, CONFIG)
    assert {v.source for v in inputs.values.values()} == {"no data loaded"}
    assert all(p.games == 0 for p in inputs.pairs.values())
    assert inputs.bombs == {}


def test_with_statistics_values_pairs_and_curated_bombs_come_from_them() -> None:
    pool, _ = three_pair_pool()
    rarity_of = {name: Rarity.COMMON for name in _snapshot().cards}
    curated = (CuratedBomb("R Bolt", "add", "", "made-up review"),)
    inputs = prepare_inputs(pool, _snapshot(), rarity_of, CONFIG, curated)
    assert inputs.values["W Creature 0"].source == "made-up games"
    assert inputs.values["W Creature 0"].games == 300
    assert inputs.values["U Creature 0"].games == 0
    assert inputs.pairs["WU"].games == 400
    assert inputs.pairs["UB"].games == 0
    assert inputs.bombs["R Bolt"] == CONFIG.bombs.threshold
