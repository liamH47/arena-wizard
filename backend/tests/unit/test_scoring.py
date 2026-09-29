"""The deck objective: incremental updates must match a full rescore, term by term."""

from __future__ import annotations

import random

import pytest

from arena_wizard.domain.scoring import load_scoring_config
from arena_wizard.domain.sets import Format
from arena_wizard.engine.scoring import DeckState, SpellFacts, state_of, terms, total

CONFIG = load_scoring_config(Format.BO1_SEALED)


def _spell(
    key: str,
    *,
    q: float = 0.0,
    creature: bool = False,
    removal: bool = False,
    mana_value: float = 3.0,
    shortfall: float = 0.0,
    bomb: float | None = None,
    splash: bool = False,
) -> SpellFacts:
    return SpellFacts(key, key, q, 1.0, creature, removal, mana_value, shortfall, bomb, splash)


def _random_spell(rng: random.Random, key: str) -> SpellFacts:
    return _spell(
        key,
        q=rng.uniform(-10, 10),
        creature=rng.random() < 0.6,
        removal=rng.random() < 0.25,
        mana_value=float(rng.randint(0, 7)),
        shortfall=rng.choice([0.0, 0.0, rng.uniform(0, 3)]),
        bomb=rng.choice([None, None, None, round(rng.uniform(2, 4), 1)]),
        splash=rng.random() < 0.1,
    )


def _check(state: DeckState, pair_points: float) -> float:
    score = total(state, pair_points, CONFIG)
    assert score == pytest.approx(sum(t.contribution for t in terms(state, pair_points, CONFIG)))
    return score


@pytest.mark.parametrize("seed", range(20))
def test_add_and_swap_deltas_equal_a_full_rescore(seed: int) -> None:
    rng = random.Random(seed)
    pool = [_random_spell(rng, f"card{i}") for i in range(45)]
    deck, bench = pool[:23], pool[23:]
    pair_points = rng.uniform(-3, 3)
    state = state_of(deck)
    for _ in range(30):
        i, j = rng.randrange(len(deck)), rng.randrange(len(bench))
        before = _check(state_of(deck), pair_points)
        swapped = state.swap(deck[i], bench[j])
        deck[i], bench[j] = bench[j], deck[i]
        after = _check(state_of(deck), pair_points)
        assert _check(swapped, pair_points) - _check(state, pair_points) == pytest.approx(
            after - before
        )
        assert swapped.bombs == state_of(deck).bombs
        state = swapped
    extra = _random_spell(rng, "extra")
    assert total(state.add(extra), pair_points, CONFIG) - total(
        state, pair_points, CONFIG
    ) == pytest.approx(
        _check(state_of([*deck, extra]), pair_points) - _check(state_of(deck), pair_points)
    )


def test_swapping_a_card_for_itself_changes_nothing() -> None:
    bomb = _spell("bomb", q=8.0, bomb=3.0, creature=True, mana_value=5.0)
    state = state_of([bomb, _spell("other")])
    assert state.swap(bomb, bomb) == state


def test_each_term_counts_what_it_says() -> None:
    w, t = CONFIG.weights, CONFIG.targets
    spells = [
        _spell("two drop", q=2.0, creature=True, mana_value=2.0),
        _spell("one drop", q=1.0, creature=True, mana_value=1.0),
        _spell("three drop", q=3.0, creature=True, mana_value=3.0),
        _spell("removal", q=4.0, removal=True, mana_value=2.0, shortfall=0.5),
        _spell("big bomb", q=9.0, creature=True, mana_value=6.0, bomb=3.0),
        _spell("small bomb", q=7.0, mana_value=5.0, bomb=2.0, splash=True, shortfall=1.5),
    ]
    state = state_of(spells)
    assert state.bombs == (3.0, 2.0)
    by_name = {term.name: term for term in terms(state, 1.5, CONFIG)}
    assert list(by_name) == [
        "card_quality",
        "pair_strength",
        "bombs",
        "creature_balance",
        "removal",
        "two_drops",
        "three_drops",
        "top_end",
        "consistency",
        "splash",
    ]
    assert by_name["card_quality"].raw == pytest.approx(26.0)
    assert by_name["pair_strength"].contribution == pytest.approx(1.5 * w.pair_strength)
    assert by_name["bombs"].raw == pytest.approx(1 + 1 / 1.5)
    assert by_name["bombs"].detail == "2 bombs"
    assert by_name["creature_balance"].raw == -(t.creatures_low - 4)
    assert by_name["creature_balance"].detail == (
        f"4 creatures (target {t.creatures_low} to {t.creatures_high})"
    )
    assert by_name["removal"].raw == 1
    assert by_name["two_drops"].raw == 2
    assert by_name["three_drops"].raw == 1
    assert by_name["top_end"].raw == -max(0, 2 - t.max_five_plus)
    assert by_name["consistency"].raw == pytest.approx(-2.0)
    assert by_name["splash"].raw == -1
    assert by_name["splash"].contribution == pytest.approx(-w.splash_card)


def test_too_many_creatures_and_expensive_spells_are_charged_and_counts_are_capped() -> None:
    t = CONFIG.targets
    creatures = [
        _spell(f"c{i}", creature=True, removal=True, mana_value=2.0 if i % 2 else 6.0)
        for i in range(t.creatures_high + 3)
    ]
    by_name = {term.name: term for term in terms(state_of(creatures), 0.0, CONFIG)}
    assert by_name["creature_balance"].raw == -3
    assert by_name["removal"].raw == t.removal_cap
    assert by_name["two_drops"].raw == t.two_drop_cap
    fives = (t.creatures_high + 3 + 1) // 2
    assert by_name["top_end"].raw == -(fives - t.max_five_plus)
    assert total(state_of(creatures), 0.0, CONFIG) == pytest.approx(
        sum(term.contribution for term in by_name.values())
    )


def test_an_empty_deck_scores_only_the_pair_and_the_creature_gap() -> None:
    w, t = CONFIG.weights, CONFIG.targets
    assert state_of([]) == DeckState()
    assert total(DeckState(), 2.0, CONFIG) == pytest.approx(
        2.0 * w.pair_strength - t.creatures_low * w.creature_balance
    )
