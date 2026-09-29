"""The evaluation report: its metrics on hand-built outcomes, and a whole set end to end.

Card names are real SOS cards from the packaged table; every statistic is made up.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import random
from collections.abc import Mapping, Sequence
from functools import cache
from typing import Any

import pytest

from arena_wizard.catalog import CardTable, load_packaged_card_table
from arena_wizard.domain.cards import Card, Color
from arena_wizard.domain.decks import CardValue, LandEntry, ScoredDeck
from arena_wizard.domain.pool import Pool, PoolEntry
from arena_wizard.domain.scoring import ScoringConfig, load_scoring_config
from arena_wizard.domain.sets import Format
from arena_wizard.domain.stats import CardCounts, PairCounts, Snapshot, SourceRef
from arena_wizard.engine.bombs import CuratedBomb
from arena_wizard.engine.builder import PAIRS, BuildInputs, pair_code
from arena_wizard.engine.resolver import CardIndex, build_index
from arena_wizard.engine.roles import Role, classify
from arena_wizard.engine.values import FormatMeans, PairValue, spell_rarities
from arena_wizard.eval.metrics import Scored
from arena_wizard.eval.records import BuildRecord, PoolRecord
from arena_wizard.eval.report import (
    NOTES,
    REPORT_FORMAT,
    PoolOutcome,
    automatic_bombs,
    bomb_section,
    build_report,
    confidence_table,
    decision_digest,
    deck_score_metrics,
    evaluate_pool,
    evaluate_set,
    is_legal,
    ledger,
    naive_picks,
    raw_deck_score,
    render_markdown,
    report_to_json,
    resolve_record,
    rounded,
    set_metrics,
    switch_metrics,
)

W, U, B, R, G = Color.WHITE, Color.BLUE, Color.BLACK, Color.RED, Color.GREEN
DAY = dt.date(2026, 5, 1)


@cache
def _table() -> CardTable:
    return load_packaged_card_table("SOS")


@cache
def _index() -> CardIndex:
    return build_index([_table()], "SOS")


@cache
def _config() -> ScoringConfig:
    return load_scoring_config(Format.BO1_SEALED)


def _spells(*colors: Color) -> list[Card]:
    """SOS's own non-land cards of exactly these colors, by collector number."""
    return sorted(
        (
            c
            for c in _table().cards
            if c.set_code == "SOS" and c.colors == colors and Role.LAND not in classify(c)
        ),
        key=lambda c: int("".join(ch for ch in c.collector_number if ch.isdigit()) or 0),
    )


def _named(name: str) -> Card:
    return _index().by_name[name]


# --- hand-built outcomes -------------------------------------------------------------


def _build(
    colors: str,
    splash: str = "",
    games: int = 4,
    wins: int = 2,
    index: int = 0,
    deck: Mapping[str, int] | None = None,
) -> BuildRecord:
    return BuildRecord(index, colors, splash, deck or {}, games, wins)


def _record(
    draft_id: str,
    *builds: BuildRecord,
    bucket: float | None = 0.64,
    games_bucket: int | None = 100,
    pool: Mapping[str, int] | None = None,
) -> PoolRecord:
    return PoolRecord(draft_id, DAY, pool or {}, builds, bucket, games_bucket)


def _deck(
    colors: str,
    total: float = 10.0,
    splash: Color | None = None,
    gap: float | None = None,
    gap_se: float | None = None,
    spells: Sequence[PoolEntry] = (),
    lands: Sequence[LandEntry] = (),
) -> ScoredDeck:
    return ScoredDeck(
        colors=colors,
        splash=splash,
        spells=tuple(spells),
        lands=tuple(lands),
        total=total,
        total_se=1.0,
        terms=(),
        values=(),
        gap_to_next=gap,
        gap_se=gap_se,
    )


NAIVE = {"best_pair": "WU", "most_playables": "WB", "raw_gih": "WB"}


def _outcome(
    record: PoolRecord,
    *decks: ScoredDeck,
    naive: Mapping[str, str] = NAIVE,
    overlap: float | None = None,
    player_total: float | None = None,
    scores: Sequence[Scored] = (),
    bombs: int = 1,
    top: Sequence[str] = ("Alpha", "Beta"),
    evaluations: int = 10,
    unresolved: int = 0,
    legal: bool = True,
) -> PoolOutcome:
    return PoolOutcome(
        record=record,
        decks=tuple(decks),
        legal=legal,
        naive=naive,
        overlap=overlap,
        player_pair_total=player_total,
        build_scores=tuple(scores),
        bombs_in_pool=bombs,
        top_cards=tuple(top),
        evaluations=evaluations,
        unresolved=unresolved,
    )


def test_an_outcome_knows_both_pairs_and_a_pool_without_decks_has_no_engine_pair() -> None:
    o = _outcome(_record("d1", _build("WB")), _deck("UR"))
    assert (o.player_pair, o.engine_pair) == ("WB", "UR")
    assert _outcome(_record("d2", _build("WB"))).engine_pair is None


# --- resolving and legality ----------------------------------------------------------


def test_a_record_resolves_by_name_and_counts_what_does_not() -> None:
    white = _spells(W)
    record = _record("d1", _build("WB"), pool={white[1].front_name: 2, "Not A Card": 1})
    pool, unresolved = resolve_record(record, _index(), "SOS")
    assert unresolved == 1
    assert [(e.card.front_name, e.count) for e in pool.entries] == [(white[1].front_name, 2)]
    assert (pool.set_code, pool.format) == ("SOS", Format.BO1_SEALED)


def _legality_case(
    spell_count: int, lands: int, pool_count: int = 30, splash: Color | None = None
) -> tuple[ScoredDeck, Pool]:
    card = _spells(W)[0]
    pool = Pool("SOS", Format.BO1_SEALED, (PoolEntry(card, pool_count),), (), ())
    deck = _deck(
        "WB",
        splash=splash,
        spells=[PoolEntry(card, spell_count)],
        lands=[LandEntry("Plains", W, lands)],
    )
    return deck, pool


@pytest.mark.parametrize(
    ("spells", "lands", "legal"),
    [(23, 17, True), (24, 16, True), (27, 17, True), (22, 17, False), (28, 17, False)],
)
def test_a_legal_deck_has_40_to_44_cards(spells: int, lands: int, legal: bool) -> None:
    assert is_legal(*_legality_case(spells, lands)) is legal


def test_a_legal_deck_has_16_or_17_lands() -> None:
    assert not is_legal(*_legality_case(25, 15))
    assert not is_legal(*_legality_case(22, 18))


def test_a_deck_may_not_play_more_copies_than_the_pool_holds() -> None:
    assert not is_legal(*_legality_case(23, 17, pool_count=22))


def test_every_spell_must_be_castable_in_the_deck_s_colors() -> None:
    red = _spells(R)[0]
    pool = Pool("SOS", Format.BO1_SEALED, (PoolEntry(red, 23),), (), ())
    spells = [PoolEntry(red, 23)]
    lands = [LandEntry("Plains", W, 17)]
    assert not is_legal(_deck("WB", spells=spells, lands=lands), pool)
    assert is_legal(_deck("WB", splash=R, spells=spells, lands=lands), pool)


# --- the naive baselines and the raw deck score ----------------------------------------


def _value(name: str, observed: float | None) -> CardValue:
    return CardValue(name, 0.0, observed, observed, 0.0, 100, "test", 1.0)


def _inputs(
    observed: Mapping[str, float | None], pairs: Mapping[str, float | None] | None = None
) -> BuildInputs:
    pairs = pairs or {}
    return BuildInputs(
        values={name: _value(name, rate) for name, rate in observed.items()},
        pairs={
            pair_code(p): PairValue(pair_code(p), 0.0, pairs.get(pair_code(p)), None, None, 0)
            for p in PAIRS
        },
        bombs={},
        config=_config(),
    )


def _pool(*entries: tuple[Card, int]) -> Pool:
    return Pool("SOS", Format.BO1_SEALED, tuple(PoolEntry(c, n) for c, n in entries), (), ())


def test_each_naive_baseline_picks_by_its_own_rule() -> None:
    white, black, red = _spells(W)[0], _spells(B)[0], _spells(R)[0]
    land = _named("Fields of Strife")
    pool = _pool((white, 20), (black, 20), (red, 3), (land, 1))
    inputs = _inputs(
        {white.front_name: 0.6, black.front_name: 0.5, red.front_name: 0.9, land.front_name: 0.99},
        pairs={"UB": 0.58, "WU": 0.55, "BG": None},
    )
    picks = naive_picks(pool, inputs, 0.5)
    # WB has 40 castable spells. WR's best 23 total 3 x 0.9 + 20 x 0.6 = 14.7, more than
    # WB's 20 x 0.6 + 3 x 0.5 = 13.5. The land is never counted.
    assert picks == {"best_pair": "UB", "most_playables": "WB", "raw_gih": "WR"}


def test_spells_without_games_count_at_the_format_mean_or_zero_without_one() -> None:
    white, green = _spells(W)[0], _spells(G)[0]
    pool = _pool((white, 1), (green, 1))
    inputs = _inputs({white.front_name: 0.5, green.front_name: None})
    assert naive_picks(pool, inputs, 0.9)["raw_gih"] == "WG"
    # With no mean, the green card counts as zero and ties go to the first pair in order.
    assert naive_picks(pool, inputs, None)["raw_gih"] == "WU"
    # With no pair records at all, the first pair in order wins.
    assert naive_picks(pool, inputs, None)["best_pair"] == "WU"


def test_the_raw_deck_score_sums_observed_rates_and_skips_lands_and_unknown_names() -> None:
    white, black, blue = _spells(W)[0], _spells(B)[0], _spells(U)[0]
    inputs = _inputs({white.front_name: 0.6, black.front_name: None})
    deck = {
        white.front_name: 2,
        black.front_name: 1,  # no games: the format mean
        blue.front_name: 1,  # not valued at all: the format mean
        "Plains": 9,
        "Not A Card": 1,
    }
    means = FormatMeans(gih=0.5, gih_by_rarity={}, gns_by_rarity={}, iwd=0.0, pair=None)
    assert raw_deck_score(deck, _index(), inputs, means) == pytest.approx(1.2 + 0.5 + 0.5)
    assert raw_deck_score(deck, _index(), inputs, None) == pytest.approx(1.2)


# --- metrics over outcomes -------------------------------------------------------------


def test_every_metric_of_an_empty_set_is_unknown_rather_than_zero() -> None:
    m = set_metrics([], [], random.Random(0))
    assert m["legality"]["value"] is None
    assert m["pair_agreement_at_1"]["n"] == 0
    assert m["pair_agreement_at_1_skill_weighted"] is None
    assert m["mean_decks_returned"] is None
    assert m["bombs_per_pool"] is None
    assert m["deck_score"]["auc_margin_over_raw_gih"]["value"] is None
    assert m["deck_score"]["slope_per_sd_skill_adjusted"] is None
    assert m["within_pool_switch"]["all"]["value"] is None
    assert m["evaluations_per_pool"] == {"mean": None, "max": 0}
    assert m["by_confidence_and_splash"] == {}


def _set_outcomes() -> list[PoolOutcome]:
    return [
        # Agrees, confident, no splash.
        _outcome(
            _record("a", _build("WB", games=5, wins=4)),
            _deck("WB", gap=5.0, gap_se=1.0),
            _deck("UR"),
            naive={"best_pair": "WB", "most_playables": "UR", "raw_gih": "WB"},
            overlap=0.8,
            evaluations=12,
        ),
        # Disagrees on a toss-up, splashing; the player's pair is second.
        _outcome(
            _record("b", _build("UR", "W", games=4, wins=1), bucket=None, games_bucket=None),
            _deck("WB", splash=R, gap=0.5, gap_se=1.0),
            _deck("UR"),
            naive={"best_pair": "WB", "most_playables": "UR", "raw_gih": "UR"},
            overlap=0.4,
            evaluations=20,
        ),
        # A three-color player: not counted for agreement, but for the shares.
        _outcome(_record("c", _build("WUB", games=3, wins=2)), _deck("WU"), bombs=3),
        # No deck at all, and illegal.
        _outcome(_record("d", _build("BG", games=2, wins=0)), legal=False, bombs=0),
    ]


def test_set_metrics_count_agreement_baselines_flips_and_shares() -> None:
    m = set_metrics(_set_outcomes(), [], random.Random(0))
    assert m["legality"]["value"] == 0.75
    assert m["pools_without_deck"] == 1
    assert (m["pair_agreement_at_1"]["value"], m["pair_agreement_at_1"]["n"]) == (1 / 3, 3)
    assert m["pair_agreement_at_3"]["value"] == 2 / 3
    # Pool b has no skill bucket, so only pools a and d are weighted.
    assert m["pair_agreement_at_1_skill_weighted"] == 0.5
    assert m["mean_decks_returned"] == 1.25
    assert m["naive_most_playables_at_1"]["value"] == 1 / 3
    assert m["flips_vs_most_playables"] == {"engine_only": 1, "baseline_only": 1}
    assert m["flips_vs_best_pair"] == {"engine_only": 0, "baseline_only": 0}
    assert m["three_color_share"]["value"] == 0.25
    assert m["player_splash_share"]["value"] == 0.25
    assert m["engine_splash_share"]["value"] == 0.25
    assert m["bombs_per_pool"] == 1.25
    assert m["deck_overlap_at_pair"]["value"] == pytest.approx(0.6)
    assert m["deck_overlap_at_pair_strong"]["value"] == 0.8
    assert m["evaluations_per_pool"] == {"mean": 13.0, "max": 20}
    assert m["agreement_lift"]["value"] == pytest.approx(4 / 5 - 1 / 6)
    assert m["by_confidence_and_splash"] == {
        "confident, no splash": {"pools": 2, "agree": 1, "most_playables_only": 0},
        "toss-up, splash": {"pools": 1, "agree": 0, "most_playables_only": 1},
    }


def test_the_confidence_table_files_a_pool_without_a_deck_as_confident() -> None:
    o = _outcome(_record("d", _build("BG")))
    assert confidence_table([o], [False]) == {
        "confident, no splash": {"pools": 1, "agree": 0, "most_playables_only": 0}
    }


def test_deck_score_metrics_compare_the_engine_with_raw_win_rates() -> None:
    outcomes = [
        _outcome(
            _record("a", _build("WB")),
            scores=[Scored(3.0, 0.0, 4, 3), Scored(1.0, 1.0, 4, 1)],
        ),
        _outcome(
            _record("b", _build("UR"), bucket=0.5, games_bucket=10),
            scores=[Scored(2.0, 2.0, 2, 1)],
        ),
        _outcome(_record("c", _build("BG"))),
    ]
    m = deck_score_metrics(outcomes, random.Random(0))
    assert (m["builds"], m["games"]) == (3, 10)
    assert m["engine_auc"] is not None and m["raw_gih_auc"] is not None
    assert m["engine_auc"] > m["raw_gih_auc"]
    assert m["auc_margin_over_raw_gih"]["n"] == 2
    # Only pool a has a known skill bucket, and its two builds cannot separate the
    # score from the constant bucket: the design is singular.
    assert m["slope_per_sd_skill_adjusted"] is None


def test_the_skill_adjusted_slope_is_fitted_when_skill_varies() -> None:
    outcomes = [
        _outcome(
            _record(f"p{i}", _build("WB"), bucket=0.4 + 0.02 * i, games_bucket=100),
            scores=[Scored(float(i % 3), 0.0, 10, 3 + i % 3 * 2)],
        )
        for i in range(9)
    ]
    slope = deck_score_metrics(outcomes, random.Random(0))["slope_per_sd_skill_adjusted"]
    assert slope is not None and slope > 0


def test_switch_metrics_pair_the_engine_s_colors_with_the_others_tried() -> None:
    first = _outcome(
        _record("a", _build("WB", games=4, wins=3), _build("UR", games=4, wins=1, index=1)),
        _deck("WB"),
    )
    later = _outcome(
        _record("b", _build("UR", games=5, wins=2), _build("WB", games=5, wins=4, index=1)),
        _deck("WB"),
    )
    one_pair = _outcome(_record("c", _build("WB"), _build("WB", index=1)), _deck("WB"))
    elsewhere = _outcome(_record("d", _build("WB"), _build("UR", index=1)), _deck("BG"))
    three = _outcome(_record("e", _build("WB"), _build("WUB", index=1)), _deck("WB"))
    m = switch_metrics([first, later, one_pair, elsewhere, three], random.Random(0))
    assert (m["engine_colors_built_first"]["value"], m["engine_colors_built_first"]["n"]) == (
        0.5,
        1,
    )
    assert m["engine_colors_built_later"]["value"] == pytest.approx(0.8 - 0.4)
    assert m["all"]["n"] == 2
    assert m["all"]["value"] == pytest.approx(7 / 9 - 3 / 9)


def test_the_ledger_lists_strong_two_color_players_the_engine_disagreed_with() -> None:
    wide = _outcome(
        _record("wide", _build("UR", games=5, wins=3), _build("WB", index=1)),
        _deck("WB", total=20.0, gap=0.5, gap_se=1.0),
        player_total=5.0,
        top=("X", "Y"),
    )
    narrow = _outcome(
        _record("narrow", _build("BG", games=3, wins=1)),
        _deck("WB", total=12.0, splash=R),
        player_total=10.0,
    )
    unbuildable = _outcome(_record("unbuildable", _build("UG")), _deck("WB"))
    skipped = [
        _outcome(_record("agrees", _build("WB")), _deck("WB")),
        _outcome(_record("weak", _build("UR"), bucket=0.5), _deck("WB")),
        _outcome(_record("few-games", _build("UR"), games_bucket=10), _deck("WB")),
        _outcome(_record("no-bucket", _build("UR"), bucket=None), _deck("WB")),
        _outcome(_record("three-color", _build("WUB")), _deck("WB")),
        _outcome(_record("no-deck", _build("UR"))),
    ]
    rows = ledger([unbuildable, narrow, *skipped, wide])
    assert [r["draft_id"] for r in rows] == ["wide", "narrow", "unbuildable"]
    assert rows[0] == {
        "draft_id": "wide",
        "player_colors": "UR",
        "player_record": "5-4",  # 3-2 as UR, then 2-2 as WB
        "engine_deck": "WB",
        "engine_total": 20.0,
        "player_colors_total": 5.0,
        "gap": 15.0,
        "toss_up": True,
        "later_switched": True,
        "top_cards": ["X", "Y"],
    }
    assert rows[1]["engine_deck"] == "WB+r" and rows[1]["later_switched"] is False
    assert rows[2]["gap"] is None


def test_the_decision_digest_changes_with_any_top_deck_and_not_with_order() -> None:
    white = _spells(W)[0]
    a = _outcome(_record("a", _build("WB")), _deck("WB", spells=[PoolEntry(white, 2)]))
    b = _outcome(_record("b", _build("WB")))
    digest = decision_digest([a, b])
    assert digest == decision_digest([b, a])
    assert len(digest) == 64
    one_copy = dataclasses.replace(a, decks=(_deck("WB", spells=[PoolEntry(white, 1)]),))
    assert decision_digest([one_copy, b]) != digest
    splashed = dataclasses.replace(a, decks=(_deck("WB", splash=R, spells=a.decks[0].spells),))
    assert decision_digest([splashed, b]) != digest


# --- bombs and rounding ------------------------------------------------------------------


def _curated(*names: str, action: str = "add") -> tuple[CuratedBomb, ...]:
    return tuple(CuratedBomb(n, action, "", "test") for n in names)


def test_bomb_names_are_withheld_until_a_curated_list_exists() -> None:
    section = bomb_section(["A", "B"], _curated("A", action="annotate"))
    assert section == {
        "automatic_count": 2,
        "automatic_names": "withheld until the set's curated list exists",
        "curated_agreement": None,
    }


def test_bomb_agreement_with_the_curated_list() -> None:
    section = bomb_section(["A", "B", "C"], _curated("A", "D"))
    assert section["automatic_names"] == ["A", "B", "C"]
    agreement = section["curated_agreement"]
    assert agreement["precision"] == pytest.approx(1 / 3)
    assert agreement["recall"] == 0.5
    assert agreement["f1"] == pytest.approx(0.4)
    assert (agreement["missed"], agreement["extra"]) == (["D"], ["B", "C"])


def test_bomb_agreement_with_no_overlap_or_no_automatic_bombs_is_zero_f1() -> None:
    assert bomb_section(["B"], _curated("A"))["curated_agreement"]["f1"] == 0.0
    empty = bomb_section([], _curated("A"))["curated_agreement"]
    assert (empty["precision"], empty["recall"], empty["f1"]) == (None, 0.0, 0.0)


def test_rounding_reaches_every_float_and_leaves_everything_else() -> None:
    value = {"a": 0.123456, "b": [1.00004, (2.5,)], "c": "x", "d": None, "e": 3, "f": True}
    assert rounded(value) == {
        "a": 0.1235,
        "b": [1.0, [2.5]],
        "c": "x",
        "d": None,
        "e": 3,
        "f": True,
    }


# --- a whole synthetic set ----------------------------------------------------------------


BOMB = "Emeritus of Truce"


def _synthetic_snapshot(games: int = 1) -> Snapshot:
    """Made-up statistics for every SOS card: `games` scales them, 0 means no data."""
    cards = {}
    for i, card in enumerate(sorted(_table().cards, key=lambda c: c.front_name)):
        gih = (400 + (i * 37) % 300) * games
        rate = 0.48 + ((i * 53) % 17) / 100
        cards[card.front_name] = CardCounts(
            gih, round(gih * rate), 400 * games, 200 * games, (gih + 400) * games, 0
        )
    pairs = {
        pair_code(p): PairCounts(1000 * games, (480 + 10 * n) * games) for n, p in enumerate(PAIRS)
    }
    # One mythic that wins far more when drawn, so the automatic list is not empty.
    cards[BOMB] = CardCounts(3000 * games, 2100 * games, 400 * games, 160 * games, 0, 0)
    total = sum(p.games for p in pairs.values()) // 2
    source = SourceRef("synthetic games", DAY, DAY, "0" * 64, total)
    return Snapshot("SOS", source, cards, pairs)


def _pool_names() -> dict[str, int]:
    cards = _spells(W) + _spells(B) + _spells(R)[:6] + _spells(B, W)
    return {c.front_name: 1 for c in cards} | {"Fields of Strife": 1, "Not A Card": 1}


def _deck_of(*colors: Color, extra: Mapping[str, int] | None = None) -> dict[str, int]:
    spells = [c.front_name for color in colors for c in _spells(color)[:12]][:23]
    return dict.fromkeys(spells, 1) | {"Plains": 8, "Swamp": 9} | dict(extra or {})


def _records() -> list[PoolRecord]:
    pool = _pool_names()
    wb = _deck_of(W, B, extra={"Not A Card": 1, _spells(U)[0].front_name: 1})
    return [
        _record(
            "strong-wb",
            _build("WB", games=5, wins=4, deck=wb),
            _build("WR", games=3, wins=1, index=1, deck=_deck_of(W, R)),
            pool=pool,
        ),
        _record(
            "three-color",
            _build("WBR", games=2, wins=1, deck=wb),
            _build("WB", "RG", games=2, wins=1, index=1, deck=wb),
            _build("WB", "R", games=3, wins=2, index=2, deck=wb | {_spells(R)[0].front_name: 1}),
            bucket=None,
            games_bucket=None,
            pool=pool,
        ),
        _record("green-blue", _build("UG", games=3, wins=0, deck=wb), bucket=0.62, pool=pool),
    ]


def _evaluate(
    records: Sequence[PoolRecord], curated: tuple[CuratedBomb, ...] = ()
) -> tuple[dict[str, Any], str]:
    return evaluate_set(
        "SOS",
        records,
        records[:1],
        _synthetic_snapshot(),
        _table(),
        _index(),
        _config(),
        curated,
        {"split_day": "2026-04-26", "sample_size": len(records), "pools": 99, "sha256": "f" * 64},
    )


@cache
def _evaluated() -> tuple[dict[str, Any], str]:
    return _evaluate(_records())


def test_a_whole_set_evaluates_to_legal_decks_for_every_pool() -> None:
    section, digest = _evaluated()
    m = section["metrics"]
    assert m["legality"]["value"] == 1.0 and m["pools_without_deck"] == 0
    assert m["unresolved_names"] == 3
    assert m["three_color_share"]["value"] == pytest.approx(1 / 3)
    assert m["deck_score"]["builds"] == 4  # the WBR build and the two-color splash are skipped
    assert section["provenance"]["split_day"] == "2026-04-26"
    assert set(section["pool_picks"]) == {"strong-wb", "three-color", "green-blue"}
    for pick in section["pool_picks"].values():
        assert 1 <= len(pick["engine"]) <= 3
        assert all(len(colors) == 2 for colors in pick["engine"])
    assert section["pool_picks"]["three-color"]["player"] == "WBR"
    assert section["bombs"]["curated_agreement"] is None
    assert len(digest) == 64


def test_the_ledger_only_holds_strong_players_the_engine_disagreed_with() -> None:
    section, _ = _evaluated()
    picks = section["pool_picks"]
    for row in section["ledger"]:
        assert row["draft_id"] != "three-color"
        assert picks[row["draft_id"]]["engine"][0] != row["player_colors"]
    green_blue = [r for r in section["ledger"] if r["draft_id"] == "green-blue"]
    assert len(green_blue) == 1
    # The pool has no green or blue cards, so the engine cannot build the player's colors.
    assert green_blue[0]["gap"] is None and green_blue[0]["player_colors_total"] is None


def test_evaluating_a_set_is_deterministic_and_the_digest_tracks_the_decisions() -> None:
    section, digest = _evaluate(_records())
    assert (section, digest) == _evaluated()
    _, fewer = _evaluate(_records()[:2])
    assert fewer != digest


def test_the_automatic_bombs_are_named_once_a_curated_list_exists() -> None:
    automatic = automatic_bombs(_synthetic_snapshot(), spell_rarities(_table().cards), _config())
    assert automatic[0] == BOMB
    section, _ = _evaluate(_records()[:1], _curated(automatic[0], "Not A Bomb"))
    bombs = section["bombs"]
    assert bombs["automatic_names"] == automatic
    assert bombs["curated_agreement"]["missed"] == ["Not A Bomb"]


def test_a_pool_evaluated_without_statistics_still_gets_legal_decks() -> None:
    empty = Snapshot("SOS", SourceRef("none", None, None, None, 0), {}, {})
    outcome = evaluate_pool(
        _records()[0],
        _index(),
        empty,
        spell_rarities(_table().cards),
        _config(),
        (),
        "SOS",
    )
    assert outcome.legal and outcome.decks
    assert outcome.bombs_in_pool == 0
    assert all(s.baseline == 0.0 for s in outcome.build_scores)


# --- the rendered report ---------------------------------------------------------------------


def _report() -> dict[str, Any]:
    section, digest = _evaluated()
    hand_built = {
        "provenance": {},
        "metrics": set_metrics(_set_outcomes(), [], random.Random(0)),
        "bombs": bomb_section(["A", "B"], _curated("A")),
        "ledger": ledger(
            [
                _outcome(
                    _record("x", _build("UR", games=2, wins=1)),
                    _deck("WB", gap=0.1, gap_se=1.0),
                    player_total=1.25,
                    top=("A", "B"),
                )
            ]
        ),
        "pool_picks": {},
    }
    return build_report({"SOS": (section, digest), "HOB": (hand_built, "0" * 64)}, _config())


def test_the_report_carries_its_versions_notes_and_rounded_sets_in_order() -> None:
    report = _report()
    assert report["report_format"] == REPORT_FORMAT
    assert report["scoring_config"] == {"version": _config().version, "sha256": _config().sha256}
    assert report["notes"] == list(NOTES)
    assert list(report["sets"]) == ["HOB", "SOS"]
    assert report_to_json(report).endswith("}\n")
    # The report's digest combines the sets' digests, so any set's decisions change it.
    same = build_report({"SOS": _evaluated(), "HOB": ({}, "0" * 64)}, _config())
    other = build_report({"SOS": _evaluated(), "HOB": ({}, "1" * 64)}, _config())
    assert same["decision_digest"] == report["decision_digest"] != other["decision_digest"]


def test_the_markdown_is_byte_stable_and_names_what_it_measures() -> None:
    report = _report()
    text = render_markdown(report)
    assert text == render_markdown(_report())
    lines = text.splitlines()
    assert lines[0] == "# Evaluation report"
    assert "## HOB" in lines and "## SOS" in lines and "## Notes" in lines
    assert lines.index("## HOB") < lines.index("## SOS")
    # The hand-built set: missing provenance, a known ledger row, and bomb names.
    assert "None sample pools of None; split day None; after the split: n/a of pools" in text
    assert "| UR | 1-1 | WB | 8.8 | yes | no | A, B |" in text
    assert "Automatic bombs: 2 (1.250 per pool); names A, B." in text
    assert "| Legal decks | 75.0% |" in text
    assert "| toss-up, splash | 1 | 0 | 1 |" in text
    # The synthetic set: withheld names, and a ledger row the engine cannot build.
    assert "names withheld until the set's curated list exists." in text
    assert "| UG | 0-3 | " in text and " | n/a | " in text
    assert text.endswith(f"- {NOTES[-1]}\n")
