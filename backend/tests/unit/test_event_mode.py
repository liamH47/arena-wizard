"""Event mode: choosing sources, the Data block, and building without the public file."""

from __future__ import annotations

import dataclasses
import datetime as dt
import random
from pathlib import Path

import pytest

from arena_wizard import commands
from arena_wizard.catalog import load_packaged_card_table
from arena_wizard.domain.decks import ValueBasis
from arena_wizard.domain.scoring import load_scoring_config
from arena_wizard.domain.sets import EventType, Format, load_set_config, packaged_set_codes
from arena_wizard.engine.bombs import CuratedBomb
from arena_wizard.engine.export_parser import parse_export
from arena_wizard.engine.grades import grade_scores
from arena_wizard.engine.resolver import build_index, resolve_pool
from arena_wizard.engine.values import spell_rarities
from arena_wizard.event_mode import (
    Sources,
    build_event,
    choose_sources,
    data_block,
    grade_inputs,
)
from arena_wizard.pastes.parsers import CardDataRow
from arena_wizard.pastes.store import StoredPaste, read_pastes, to_snapshot
from tests.unit.test_paste_commands import (
    DAY,
    ad_request,
    card_data_csv,
    grades_csv,
    request,
    run_paste,
)

FRA = load_set_config("FRA")
EVENT = load_scoring_config(Format.BO1_SEALED).event
DRAFT = request("card-data", "17lands-card-data", EventType.PREMIER_DRAFT)
SEALED = request("card-data", "17lands-card-data", EventType.SEALED)
PUBLIC = "17Lands public Premier Draft game data"


def _stored(tmp_path: Path, *pastes: tuple[object, bytes, dt.date]) -> tuple[StoredPaste, ...]:
    data = tmp_path / "data"
    for req, body, day in pastes:
        status, lines = run_paste(req, body, data, day)  # type: ignore[arg-type]
        assert status == 0, lines
    stored, stale = read_pastes(data, "FRA")
    assert stale == ()
    return stored


def _by(pastes: tuple[StoredPaste, ...], source: str, day: dt.date) -> StoredPaste:
    return next(p for p in pastes if p.key.source_id == source and p.key.import_day == day)


LATER = DAY + dt.timedelta(days=1)


# --- choosing sources -----------------------------------------------------------------------


def test_the_newest_paste_of_each_kind_is_chosen_and_the_rest_say_why(tmp_path: Path) -> None:
    pastes = _stored(
        tmp_path,
        (request(), grades_csv(seed=1), DAY),
        (request(), grades_csv(seed=2), LATER),
        (request(source="llu-alex"), grades_csv(seed=3), DAY),
        (ad_request(), card_data_csv(seed=1), DAY),
        (ad_request(), card_data_csv(seed=2), LATER),
        (SEALED, card_data_csv(seed=3), LATER),
        (DRAFT, card_data_csv(seed=4, draft=True), DAY),
    )
    sources = choose_sources(pastes, None, PUBLIC, frozenset())
    assert [(p.key.source_id, p.key.import_day) for p in sources.grades] == [
        ("llu-alex", DAY),
        ("llu-marc", LATER),
    ]
    assert sources.direct is not None and sources.direct.key.import_day == LATER
    assert sources.direct.key.event_type is EventType.ARENA_DIRECT_SEALED
    assert sources.proxy is not None and sources.proxy_name is not None
    assert sources.proxy_name.startswith("17Lands card data, Premier Draft, pasted by hand")
    reasons = {(p.key.event_type, p.key.import_day): why for p, why in sources.not_used}
    assert reasons == {
        (None, DAY): "a newer paste from this source is used",
        (EventType.ARENA_DIRECT_SEALED, DAY): "a newer paste from this source is used",
        (EventType.SEALED, LATER): "the Arena Direct paste is preferred",
    }


def test_the_public_draft_file_beats_a_draft_paste(tmp_path: Path) -> None:
    pastes = _stored(tmp_path, (DRAFT, card_data_csv(draft=True), DAY))
    public = to_snapshot(pastes[0])
    sources = choose_sources(pastes, public, PUBLIC, frozenset())
    assert (sources.proxy, sources.proxy_name) == (public, PUBLIC)
    assert [why for _, why in sources.not_used] == ["the public Premier Draft file is used instead"]


def test_a_covered_paste_is_never_chosen(tmp_path: Path) -> None:
    pastes = _stored(tmp_path, (DRAFT, card_data_csv(draft=True), DAY))
    sources = choose_sources(pastes, None, PUBLIC, frozenset({EventType.PREMIER_DRAFT}))
    assert sources.proxy is None and sources.proxy_name is None
    assert [why for _, why in sources.not_used] == ["the public file replaces it"]


def test_a_sealed_paste_stands_in_when_there_is_no_arena_direct_paste(tmp_path: Path) -> None:
    pastes = _stored(tmp_path, (SEALED, card_data_csv(), DAY))
    sources = choose_sources(pastes, None, PUBLIC, frozenset())
    assert sources.direct is pastes[0] and sources.not_used == ()
    assert choose_sources((), None, PUBLIC, frozenset()) == Sources((), None, None, None, ())


def test_grade_inputs_keep_graded_cards_only(tmp_path: Path) -> None:
    (paste,) = _stored(tmp_path, (request(), grades_csv(tbd=3), DAY))
    (source,) = grade_inputs((paste,))
    assert source.label == "Marc Anderson, Limited Level-Ups"
    ungraded = {r.name for r in paste.grade_rows if r.value is None}
    assert ungraded and not ungraded & source.values.keys()
    assert source.raw.keys() == source.values.keys()


# --- the Data block -------------------------------------------------------------------------


def test_with_nothing_the_data_block_lists_every_missing_source_and_its_command() -> None:
    lines = data_block(FRA, EVENT, Sources((), None, None, None, ()), None, (), DAY, False)
    assert lines[0] == "FRA data for this build (FRA reached Arena 2026-09-29):"
    text = "\n".join(lines)
    for expected in (
        "  Win rates    missing  ",
        "--event-type ArenaDirect_Sealed --source 17lands-card-data --file PATH",
        "  Draft data   missing  Sign in to 17Lands",
        "--event-type PremierDraft --source 17lands-card-data --file PATH",
        "  Grades       missing  arena-wizard paste --set FRA --dataset grades",
        "  Bombs        missing  The automatic list needs 500+ games in hand per card",
        "  Public file  missing  17Lands publishes it weeks after release",
        "17Lands asks tools not to show FRA data before 2026-10-10",
    ):
        assert expected in text
    after = data_block(
        FRA, EVENT, Sources((), None, None, None, ()), None, (), FRA.embargo_until, True
    )
    assert "  Public file  embargoed" in "\n".join(after)
    assert not any("asks tools not to show" in line for line in after)


def test_with_every_source_the_data_block_says_what_is_used_and_what_is_not(
    tmp_path: Path,
) -> None:
    pastes = _stored(
        tmp_path,
        (request(published_on=dt.date(2026, 9, 20)), grades_csv(seed=1), DAY),
        (request(source="llu-alex"), grades_csv(seed=2), DAY),
        (ad_request(), card_data_csv(seed=1), DAY),
        (SEALED, card_data_csv(seed=3), DAY),
        (DRAFT, card_data_csv(seed=4, draft=True), DAY),
    )
    sources = choose_sources(pastes, None, PUBLIC, frozenset())
    rarity_of = spell_rarities(load_packaged_card_table("FRA").cards)
    scores = grade_scores(grade_inputs(sources.grades), rarity_of)
    curated = (
        CuratedBomb("Gideon the Oathless", "add", "", "own"),
        CuratedBomb("Consider", "remove", "", "own"),
    )
    text = "\n".join(data_block(FRA, EVENT, sources, scores, curated, DAY, False))
    assert "  Win rates    used     17Lands card data, Arena Direct Sealed, pasted by hand" in text
    assert "game-in-hand counts " in text and "date range not recorded" in text
    assert "  Draft data   used     17Lands card data, Premier Draft" in text
    assert "draft results used as a proxy for sealed" in text
    assert "Marc Anderson, Limited Level-Ups, copied 2026-10-03, published 2026-09-20: " in text
    assert "Alex Nikolic, Limited Level-Ups, copied 2026-10-03: " in text
    assert "assumed, not yet tested against results" in text
    assert "  Bombs        used     The group's curated list (1 cards)." in text
    assert "  Not used     17Lands card data, Sealed, pasted by hand" in text
    assert "the Arena Direct paste is preferred." in text


def test_a_paste_whose_rows_have_no_games_is_described_as_such(tmp_path: Path) -> None:
    (paste,) = _stored(tmp_path, (ad_request(), card_data_csv(), DAY))
    empty = dataclasses.replace(paste, card_rows=(CardDataRow("X", "", None, 0, None, 0, None),))
    lines = data_block(FRA, EVENT, Sources((), None, None, empty, ()), None, (), DAY, False)
    assert "                        no cards with games; date range not recorded." in lines


# --- building --------------------------------------------------------------------------------


def _fra_pool_text(size: int = 83, seed: int = 7) -> str:
    cards = [c for c in load_packaged_card_table("FRA").cards if not c.is_basic]
    picked = random.Random(seed).sample(cards, size)
    return "\n".join(f"1 {c.name} ({c.set_code}) {c.collector_number}" for c in picked)


def _build(pastes: tuple[StoredPaste, ...], text: str | None = None) -> tuple[int, list[str]]:
    lines: list[str] = []
    data = commands.BuildData(pastes=pastes)
    status = commands.build(
        "FRA", Format.BO1_SEALED, text or _fra_pool_text(), data, DAY, lines.append
    )
    return status, lines


def test_with_no_values_at_all_the_build_refuses_after_the_data_block() -> None:
    status, lines = _build(())
    assert status == 1
    assert lines[1].startswith("FRA data for this build")
    assert lines[-1].startswith("No card values for FRA, so no deck is ranked.")
    assert not any(line.startswith("#") for line in lines)


def test_grades_alone_rank_decks_without_claiming_a_measured_lead(tmp_path: Path) -> None:
    pastes = _stored(tmp_path, (request(), grades_csv(), DAY))
    status, lines = _build(pastes)
    assert status == 0
    ranks = [line for line in lines if line.startswith("#")]
    assert 1 <= len(ranks) <= 5
    assert "  Values: " in "\n".join(lines) and " from draft grades" in "\n".join(lines)
    assert not any("Ahead of" in line for line in lines)
    assert (
        any("Ranked above" in line or "Within grade uncertainty" in line for line in lines)
        or len(ranks) == 1
    )
    assert lines.count("  Card values (points; ± is the uncertainty):") == 1
    assert any("from draft grades (Marc Anderson, Limited Level-Ups " in line for line in lines)
    assert any("Bombs: not assessed." in line for line in lines)


@pytest.mark.parametrize(
    ("req", "body", "weight"),
    [
        (DRAFT, card_data_csv(draft=True), "draft data"),
        (ad_request(), card_data_csv(), "Arena Direct"),
    ],
    ids=["draft", "arena-direct"],
)
def test_win_rates_rank_decks_and_show_each_layers_weight(
    tmp_path: Path, req: object, body: bytes, weight: str
) -> None:
    pastes = _stored(tmp_path, (req, body, DAY))
    status, lines = _build(pastes)
    assert status == 0
    values = [line for line in lines if "% in hand (n=" in line]
    assert values and all(f"{weight} " in line for line in values)
    # With no grades, each card's prior is its rarity's average in the pasted data.
    assert all(" average" in line for line in values)


def test_draft_win_rates_with_enough_games_feed_the_automatic_list(tmp_path: Path) -> None:
    pastes = _stored(tmp_path, (DRAFT, card_data_csv(draft=True), DAY))
    status, lines = _build(pastes)
    assert status == 0
    # Made-up rates are flat, so the list is computed but no card clears the bar.
    assert "  Bombs        used     Automatic from draft data (none reach the bomb bar)." in lines


def test_the_bombs_line_joins_automatic_and_curated_sources() -> None:
    nothing = Sources((), None, None, None, ())
    curated = (CuratedBomb("X", "add", "", "group vote"),)
    lines = data_block(FRA, EVENT, nothing, None, curated, DAY, False, auto=("Arena Direct", 3))
    assert (
        "  Bombs        used     Automatic from Arena Direct (3 cards); the group's curated "
        "list (1 cards)." in lines
    )


def test_a_pool_too_small_for_any_deck_says_so(tmp_path: Path) -> None:
    pastes = _stored(tmp_path, (request(), grades_csv(), DAY))
    status, lines = _build(pastes, _fra_pool_text(size=5))
    assert status == 1
    assert lines[-1] == "No color pair has enough castable spells for a 40-card deck."


def test_a_curated_list_names_its_bombs_in_the_decks(tmp_path: Path) -> None:
    pastes = _stored(tmp_path, (request(), grades_csv(), DAY))
    home = load_packaged_card_table("FRA")
    others = [load_packaged_card_table(c) for c in packaged_set_codes() if c != "FRA"]
    pool = resolve_pool(
        parse_export(_fra_pool_text()),
        FRA,
        build_index([home], "FRA"),
        build_index(others),
        Format.BO1_SEALED,
    )
    names = sorted(e.card.front_name for e in pool.entries)
    curated = tuple(CuratedBomb(n, "add", "", "own") for n in names)
    lines: list[str] = []
    status = build_event(
        FRA,
        pool,
        spell_rarities(home.cards),
        choose_sources(pastes, None, PUBLIC, frozenset()),
        load_scoring_config(Format.BO1_SEALED, "FRA"),
        curated,
        DAY,
        False,
        lines.append,
    )
    assert status == 0
    assert any(line.startswith("  Bombs: ") and "(the group's list)" in line
               for line in lines)  # fmt: skip
    assert ValueBasis.GRADES.value == "grades"
