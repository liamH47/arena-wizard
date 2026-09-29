from __future__ import annotations

import dataclasses
import datetime as dt
from collections.abc import Collection, Mapping

from arena_wizard.domain.decks import LandEntry, ScoredDeck, ScoreTerm
from arena_wizard.domain.pool import PoolEntry
from arena_wizard.domain.stats import SourceRef
from arena_wizard.engine.builder import build_decks
from arena_wizard.engine.explain import arena_list, describe, pair_sentence, window
from arena_wizard.engine.values import PairValue
from tests.engine_fixture import (
    R,
    W,
    card,
    make_inputs,
    no_pairs,
    removal,
    three_pair_pool,
    value,
)

SOURCE = SourceRef("made-up games", dt.date(2026, 5, 1), dt.date(2026, 5, 30), None, 900)
WINDOW = "made-up games, 2026-05-01 to 2026-05-30"


def _term(name: str, contribution: float, detail: str = "") -> ScoreTerm:
    return ScoreTerm(name, contribution, 1.0, contribution, detail or name)


def _deck(
    names: list[str],
    *,
    total: float = 10.0,
    terms: tuple[ScoreTerm, ...] = (),
    colors: str = "WU",
) -> ScoredDeck:
    spells = tuple(PoolEntry(card(n, "{1}{W}"), 1) for n in names)
    return ScoredDeck(
        colors=colors,
        splash=None,
        spells=spells,
        lands=(LandEntry("Plains", W, 17),),
        total=total,
        total_se=1.0,
        terms=terms or (_term("card_quality", total),),
        values=tuple(value(n, 0.0) for n in names),
    )


def _sentences(
    *decks: ScoredDeck,
    pairs: Mapping[str, PairValue] | None = None,
    bombs: Mapping[str, float] | None = None,
    source: SourceRef | None = SOURCE,
    curated: Collection[str] = (),
    pair_weight: float = 1.0,
) -> list[tuple[str, ...]]:
    described = describe(
        decks, pairs or no_pairs(), bombs or {}, source, curated=curated, pair_weight=pair_weight
    )
    return [d.explanations for d in described]


def test_the_window_names_the_source_and_its_dates() -> None:
    assert window(SOURCE) == WINDOW


def test_the_window_says_nothing_is_loaded_without_a_source_or_dates() -> None:
    assert window(None) == "no statistics loaded"
    assert window(dataclasses.replace(SOURCE, first_day=None)) == "no statistics loaded"


def test_a_pair_with_no_games_says_it_has_no_record() -> None:
    pair = PairValue("WU", 0.0, None, None, None, 0)
    assert pair_sentence(pair, SOURCE) == f"WU decks: no record in {WINDOW}."


def test_a_pair_that_is_mostly_data_shows_only_the_rate_used() -> None:
    pair = PairValue("WU", 1.2, 0.571, 0.562, 0.1, 2_400)
    assert pair_sentence(pair, SOURCE) == (
        f"WU decks: 56.2% win rate (n=2,400, 10% prior) in {WINDOW}."
    )


def test_a_pair_that_is_mostly_prior_shows_observed_and_used() -> None:
    pair = PairValue("WU", 0.4, 0.62, 0.55, 0.6, 200)
    assert pair_sentence(pair, SOURCE) == (
        f"WU decks: 62.0% observed, 55.0% after shrinkage win rate (n=200, 60% prior) in {WINDOW}."
    )


def test_a_rate_with_no_value_reads_not_available() -> None:
    pair = PairValue("WU", 0.0, None, None, None, 10)
    assert pair_sentence(pair, SOURCE) == f"WU decks: n/a win rate (n=10, 0% prior) in {WINDOW}."


def test_the_pair_sentence_leads_when_statistics_are_loaded_and_the_pair_term_counts() -> None:
    pairs = no_pairs()
    pairs["WU"] = PairValue("WU", 1.2, 0.571, 0.562, 0.1, 2_400)
    (sentences,) = _sentences(_deck(["A"]), pairs=pairs)
    assert sentences[0].startswith("WU decks: 56.2% win rate")


def test_a_zero_pair_weight_leaves_the_pair_sentence_out() -> None:
    (sentences,) = _sentences(_deck(["A"]), pair_weight=0.0)
    assert not any(s.startswith("WU decks") for s in sentences)


def test_values_that_are_mostly_prior_and_cards_with_no_games_are_named() -> None:
    thin = dataclasses.replace(value("Thin", 3.0, games=40), prior_share=0.8, observed=0.7)
    firm = value("Firm", 5.0, games=4_000)
    missing = [value(f"Unseen {i}", 0.0, games=0) for i in range(7)]
    deck = dataclasses.replace(_deck(["A"]), values=(thin, firm, *missing))
    (sentences,) = _sentences(deck, pair_weight=0.0)
    assert sentences == (
        "Mostly prior: Thin 70.0% observed, 55.0% used (n=40, 80% prior).",
        "No games in the statistics: Unseen 0, Unseen 1, Unseen 2, Unseen 3, Unseen 4, "
        "and 2 more. Each is valued at its rarity's average.",
    )


def test_without_statistics_nothing_is_presented_as_data() -> None:
    thin = dataclasses.replace(value("Thin", 3.0, games=40), prior_share=0.8)
    deck = dataclasses.replace(_deck(["A"]), values=(thin,))
    (sentences,) = _sentences(deck, source=None)
    assert sentences == ()


def test_bombs_are_labelled_automatic_or_curated() -> None:
    deck = _deck(["Auto Bomb", "Group Bomb", "Plain"])
    bombs = {"Auto Bomb": 2.4, "Group Bomb": 2.0, "Not In Deck": 3.0}
    (sentences,) = _sentences(deck, bombs=bombs, curated={"Group Bomb"}, pair_weight=0.0)
    assert sentences == (
        f"Bombs: Auto Bomb (automatic, from {WINDOW}); Group Bomb (the group's curated list).",
    )


def test_a_deck_of_only_automatic_or_only_curated_bombs_names_one_kind() -> None:
    (auto,) = _sentences(_deck(["X"]), bombs={"X": 2.5}, pair_weight=0.0)
    (group,) = _sentences(_deck(["X"]), bombs={"X": 2.0}, curated={"X"}, pair_weight=0.0)
    assert auto == (f"Bombs: X (automatic, from {WINDOW}).",)
    assert group == ("Bombs: X (the group's curated list).",)


def test_a_splash_names_its_cards_and_land_sources() -> None:
    bolt = PoolEntry(removal("R Bolt", "{R}"), 1)
    deck = dataclasses.replace(
        _deck(["A"]), splash=R, spells=(bolt, *_deck(["A"]).spells), sources=((W, 14), (R, 3))
    )
    (sentences,) = _sentences(deck, pair_weight=0.0)
    assert sentences == ("Splashes R Bolt off 3 red land sources.",)


def test_a_clear_lead_states_the_gap_its_error_and_the_largest_differences() -> None:
    first = dataclasses.replace(
        _deck(
            ["Shared", "Only First"],
            total=20.0,
            terms=(
                _term("card_quality", 15.0),
                _term("removal", 3.0, "5 removal"),
                _term("bombs", 2.0),
            ),
        ),
        gap_to_next=6.0,
        gap_se=2.0,
    )
    second = _deck(
        ["Shared", "Only Second"],
        total=14.0,
        terms=(
            _term("card_quality", 12.0),
            _term("removal", 0.0, "0 removal"),
            _term("bombs", 2.0),
        ),
        colors="WB",
    )
    first_sentences, second_sentences = _sentences(first, second, pair_weight=0.0)
    assert first_sentences == (
        "Ahead of WB by 6.0 score points (standard error 2.0, from sample sizes only). "
        "Largest differences: card values +3.0 (sum +15.0 here, +12.0 there); "
        "removal +3.0 (5 removal here, 0 removal there). "
        "Cards only here: Only First; only there: Only Second.",
    )
    assert second_sentences == ()


def test_a_gap_within_one_standard_error_is_called_a_toss_up() -> None:
    first = dataclasses.replace(_deck(["A"], total=10.5), gap_to_next=0.5, gap_se=2.0)
    second = _deck(["A"], total=10.0)
    (sentences, _) = _sentences(first, second, pair_weight=0.0)
    assert sentences == (
        "Within one standard error of WU: treat the order as a toss-up. "
        "Largest differences: card values +0.5 (sum +10.5 here, +10.0 there).",
    )


def test_without_statistics_a_lead_is_on_deck_shape_alone() -> None:
    first = dataclasses.replace(_deck(["A"], total=10.0), gap_to_next=0.0, gap_se=0.0)
    second = _deck(["B"], total=10.0)
    (sentences, _) = _sentences(first, second, source=None)
    assert sentences == (
        "Ahead of WU by 0.0 on deck shape alone. Cards only here: A; only there: B.",
    )


def test_a_missing_gap_reads_as_zero_and_a_deck_with_one_side_of_differences_names_it() -> None:
    first = _deck(["A", "B"])
    second = _deck(["A"])
    (sentences, _) = _sentences(first, second, source=None)
    assert sentences == ("Ahead of WU by 0.0 on deck shape alone. Cards only here: B.",)
    (reverse, _) = _sentences(second, first, source=None)
    assert reverse == ("Ahead of WU by 0.0 on deck shape alone. Cards only there: B.",)


def test_describe_explains_real_builder_output_with_every_deck_compared_to_the_next() -> None:
    pool, q = three_pair_pool()
    inputs = make_inputs(pool, q)
    decks = build_decks(pool, inputs).decks
    described = describe(decks, inputs.pairs, inputs.bombs, SOURCE)
    assert [d.label for d in described] == [d.label for d in decks]
    for deck, nxt in zip(described, described[1:], strict=False):
        assert f" of {nxt.label}" in deck.explanations[-1]
    assert described[0].explanations[0] == f"WU decks: no record in {WINDOW}."


def test_the_arena_list_puts_creatures_then_spells_by_cost_and_name_then_lands() -> None:
    spells = (
        PoolEntry(card("Zebra", "{1}{W}"), 2),
        PoolEntry(card("Aardvark", "{1}{W}"), 1),
        PoolEntry(card("Titan", "{5}{W}"), 1),
        PoolEntry(removal("Smite", "{W}"), 1),
        PoolEntry(removal("Banish", "{3}{W}"), 1),
    )
    deck = dataclasses.replace(
        _deck(["unused"]),
        spells=spells,
        lands=(LandEntry("Plains", W, 9), LandEntry("Island", None, 8)),
    )
    assert arena_list(deck) == "\n".join(
        [
            "1 Aardvark",
            "2 Zebra",
            "1 Titan",
            "1 Smite",
            "1 Banish",
            "9 Plains",
            "8 Island",
        ]
    )
