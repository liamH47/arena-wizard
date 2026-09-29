"""Checks a paste must pass before anything is stored (decision 0007). Made-up numbers."""

from __future__ import annotations

import pytest

from arena_wizard.domain.sets import EventType
from arena_wizard.pastes.check import PasteRefused, check_card_data, check_grades
from arena_wizard.pastes.names import name_index
from arena_wizard.pastes.parsers import CardDataRow, CardDataTable, GradeRow, GradeTable
from tests.unit.test_lands import card

NAMES = [f"Card {i:02}" for i in range(20)]
INDEX = name_index(card(n) for n in NAMES)
SPELLS = frozenset(NAMES)
FULL = ("Name", "Color", "Rarity", "# GIH", "GIH WR", "# GNS", "GNS WR")
AD = EventType.ARENA_DIRECT_SEALED


def _row(name: str, games: int | None = 100, rate: float | None = 0.55) -> CardDataRow:
    return CardDataRow(name, "W", "C", games, rate, 40, 0.5)


def _cards(
    rows: list[CardDataRow], columns: tuple[str, ...] = FULL, draft: bool = False
) -> CardDataTable:
    return CardDataTable(columns, tuple(rows), draft)


def _grades(rows: list[GradeRow]) -> GradeTable:
    return GradeTable("Tier", "letter", tuple(rows))


def _check(table: CardDataTable, event: EventType = AD) -> object:
    return check_card_data(table, event, INDEX, SPELLS, "TST")


def test_a_full_export_passes_with_names_renamed_and_sorted() -> None:
    rows = [_row(n.lower()) for n in reversed(NAMES)]
    checked = check_card_data(_cards(rows), AD, INDEX, SPELLS, "TST")
    assert [r.name for r in checked.rows] == NAMES
    assert checked.unknown == () and checked.warnings == ()


def test_a_few_unknown_names_are_skipped_and_reported() -> None:
    rows = [_row(n) for n in NAMES] + [_row("Plan for All Outcomes")]
    checked = check_card_data(_cards(rows), AD, INDEX, SPELLS, "TST")
    assert checked.unknown == ("Plan for All Outcomes",) and len(checked.rows) == 20


def test_text_from_another_set_is_refused() -> None:
    rows = [_row(n) for n in NAMES[:17]] + [_row(f"Other {i}") for i in range(3)]
    with pytest.raises(PasteRefused, match="3 of 20 names are not TST cards"):
        _check(_cards(rows))


@pytest.mark.parametrize("damaged", ["Card ?? Mangled", "D�in"])
def test_names_damaged_by_an_encoding_are_refused(damaged: str) -> None:
    rows = [_row(n) for n in NAMES] + [_row(damaged)]
    with pytest.raises(PasteRefused, match="damaged on the way in"):
        _check(_cards(rows))


def test_a_filtered_export_covering_too_few_spells_is_refused() -> None:
    with pytest.raises(PasteRefused, match="covers 15 of TST's 20 spells"):
        _check(_cards([_row(n) for n in NAMES[:15]]))


def test_eighty_percent_coverage_is_enough() -> None:
    assert (
        len(check_card_data(_cards([_row(n) for n in NAMES[:16]]), AD, INDEX, SPELLS, "TST").rows)
        == 16
    )


def test_a_header_only_export_is_refused_for_coverage() -> None:
    with pytest.raises(PasteRefused, match="covers 0 of"):
        _check(_cards([]))


@pytest.mark.parametrize(
    "rows",
    [
        [_row(n, games=None, rate=None) for n in NAMES],
        [_row(n, games=0) for n in NAMES],
        [_row(n, rate=None) for n in NAMES],
    ],
)
def test_an_export_with_no_game_in_hand_games_is_refused(rows: list[CardDataRow]) -> None:
    with pytest.raises(PasteRefused, match="no card has any game-in-hand games"):
        _check(_cards(rows))


@pytest.mark.parametrize("event", [AD, EventType.SEALED])
def test_draft_pick_columns_on_a_sealed_paste_are_refused(event: EventType) -> None:
    with pytest.raises(PasteRefused, match="pass --event-type PremierDraft"):
        _check(_cards([_row(n) for n in NAMES], draft=True), event)


def test_draft_pick_columns_are_expected_on_a_premier_draft_paste() -> None:
    table = _cards([_row(n) for n in NAMES], draft=True)
    assert len(check_card_data(table, EventType.PREMIER_DRAFT, INDEX, SPELLS, "TST").rows) == 20


def test_an_event_type_that_is_not_card_data_is_refused() -> None:
    with pytest.raises(PasteRefused, match="must be Arena Direct Sealed"):
        _check(_cards([_row(n) for n in NAMES]), EventType.TRAD_SEALED)


def test_a_card_twice_with_different_numbers_is_refused_and_exact_repeats_collapse() -> None:
    rows = [_row(n) for n in NAMES] + [_row("Card 00")]
    assert len(check_card_data(_cards(rows), AD, INDEX, SPELLS, "TST").rows) == 20
    with pytest.raises(PasteRefused, match="Card 00 appears twice"):
        _check(_cards([*rows, _row("card 00", games=7)]))


def test_an_export_without_not_seen_columns_warns_that_it_uses_in_hand_rates_only() -> None:
    columns = ("Name", "# GIH", "GIH WR")
    checked = check_card_data(_cards([_row(n) for n in NAMES], columns), AD, INDEX, SPELLS, "T")
    assert len(checked.warnings) == 1 and "Not Seen" in checked.warnings[0]


def _graded(count: int, value: float | None = None) -> list[GradeRow]:
    return [
        GradeRow(n, "B", float(i % 5) if value is None else value)
        for i, n in enumerate(NAMES[:count])
    ]


def test_a_grade_list_covering_enough_spells_passes() -> None:
    rows = [*_graded(16), GradeRow("Card 19", "TBD", None), GradeRow("Stranger", "A", 12.0)]
    checked = check_grades(_grades(rows), INDEX, SPELLS, "TST", 0.8)
    assert len(checked.rows) == 17 and checked.unknown == ("Stranger",)


def test_a_grade_list_covering_too_few_spells_is_refused() -> None:
    rows = [*_graded(15), *(GradeRow(n, "TBD", None) for n in NAMES[15:])]
    with pytest.raises(PasteRefused, match="grades 15 of TST's 20 spells"):
        check_grades(_grades(rows), INDEX, SPELLS, "TST", 0.8)


def test_a_grade_list_where_every_grade_is_equal_is_refused() -> None:
    with pytest.raises(PasteRefused, match="every grade in the list is the same"):
        check_grades(_grades(_graded(20, value=8.0)), INDEX, SPELLS, "TST", 0.8)


def test_a_single_graded_card_cannot_rank_anything() -> None:
    with pytest.raises(PasteRefused, match="every grade in the list is the same"):
        check_grades(_grades(_graded(1)), INDEX, frozenset(NAMES[:1]), "TST", 0.5)
