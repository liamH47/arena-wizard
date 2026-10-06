"""The paste parsers, on made-up numbers in 17Lands' real export layouts (decision 0005)."""

from __future__ import annotations

import pytest

from arena_wizard.pastes.parsers import (
    CardDataRow,
    GradeRow,
    ShapeError,
    parse_card_data,
    parse_grades,
)

FULL_HEADER = [
    "Name",
    "Color",
    "Rarity",
    "# Seen",
    "ALSA",
    "# Picked",
    "ATA",
    "# GP",
    "% GP",
    "GP WR",
    "# OH",
    "OH WR",
    "# GD",
    "GD WR",
    "# GIH",
    "GIH WR",
    "# GNS",
    "GNS WR",
    "IIH",
]


def _csv(*rows: list[str]) -> str:
    """Build text the way 17Lands' Download as CSV does: BOM, every cell quoted, no final
    newline."""
    lines = [",".join(f'"{cell}"' for cell in row) for row in (FULL_HEADER, *rows)]
    return "﻿" + "\n".join(lines)


def _clipboard(*rows: list[str]) -> str:
    """Build text the way Copy to clipboard does: tabs, no quotes, no final newline."""
    return "\n".join("\t".join(row) for row in (FULL_HEADER, *rows))


ROW = [
    "Made-up Knight, of Commas",
    "W",
    "C",
    "900",
    "5.10",
    "300",
    "6.20",
    "800",
    "70.0%",
    "55.0%",
    "300",
    "56.0%",
    "400",
    "57.5%",
    "700",
    "57.0%",
    "250",
    "52.4%",
    "4.6pp",
]
COLORLESS = [
    "Made-up Relic // Other Side",
    "",
    "U",
    "10",
    "8.00",
    "3",
    "9.00",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
]
EXPECTED = (
    CardDataRow("Made-up Knight, of Commas", "W", "C", 700, 0.57, 250, 0.524),
    CardDataRow("Made-up Relic // Other Side", "", "U", None, None, None, None),
)


@pytest.mark.parametrize("build", [_csv, _clipboard])
def test_both_export_layouts_parse_to_the_same_rows(build: object) -> None:
    table = parse_card_data(build(ROW, COLORLESS))  # type: ignore[operator]
    assert table.rows == EXPECTED
    assert table.columns == tuple(FULL_HEADER)


def test_windows_line_endings_and_a_trailing_newline_are_ignored() -> None:
    text = _clipboard(ROW).replace("\n", "\r\n") + "\r\n"
    assert parse_card_data(text).rows == EXPECTED[:1]


def test_a_spreadsheet_resave_without_quotes_still_parses_names_with_commas() -> None:
    header = "Name,Color,Rarity,# GIH,GIH WR"
    text = header + '\n"Made-up Knight, of Commas",W,C,1200,"55.0%"\nPlain Card,B,M,,'
    rows = parse_card_data(text).rows
    assert rows[0] == CardDataRow("Made-up Knight, of Commas", "W", "C", 1200, 0.55, None, None)
    assert rows[1] == CardDataRow("Plain Card", "B", "M", None, None, None, None)


def test_thousands_separators_and_not_a_number_rates_are_handled() -> None:
    text = "Name\t# GIH\tGIH WR\nCard\t1,204\tNaN%"
    assert parse_card_data(text).rows == (CardDataRow("Card", "", None, 1204, None, None, None),)


def test_an_export_without_the_in_hand_columns_says_what_to_tick() -> None:
    phone_default = (
        "Name\tColor\tRarity\t# Seen\tALSA\t# Picked\tATA\tIIH\nCard\tW\tC\t1\t2\t3\t4\t1pp"
    )
    with pytest.raises(ShapeError, match="tick Ever in Hand"):
        parse_card_data(phone_default)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("", "empty"),
        ("﻿\n\n", "empty"),
        ("Name\t# GIH\tGIH WR\nCard\t12", "line 2 has 2 cells"),
        ("Name\t# GIH\tGIH WR\n\t12\t50.0%", "no card name"),
        ("Name\t# GIH\tGIH WR\nCard\ttwelve\t50.0%", "whole number"),
        ("Name\t# GIH\tGIH WR\nCard\t12\thalf", "55.2%"),
    ],
)
def test_malformed_exports_are_refused_with_a_reason(text: str, message: str) -> None:
    with pytest.raises(ShapeError, match=message):
        parse_card_data(text)


def test_letter_tiers_rank_worst_to_best_with_sideboard_below_f() -> None:
    text = (
        "Name,Tier,Buildaround,Synergy,Comment\n"
        "Bomb,A+,,,\nFiller,C,,,\nBad,F,,,\nUnplayable,SB,,,\nUnknown,TBD,,,\nLower,b-,,,"
    )
    table = parse_grades(text)
    assert table.scale == "letter" and table.column == "Tier"
    assert table.rows == (
        GradeRow("Bomb", "A+", 12.0),
        GradeRow("Filler", "C", 5.0),
        GradeRow("Bad", "F", 0.0),
        GradeRow("Unplayable", "SB", -1.0),
        GradeRow("Unknown", "TBD", None),
        GradeRow("Lower", "b-", 7.0),
    )


def test_numeric_grades_keep_their_values_and_blanks_are_ungraded() -> None:
    table = parse_grades("name\tgrade\nA Card\t3.5\nB Card\t\nC Card\t0")
    assert table.scale == "number"
    assert [r.value for r in table.rows] == [3.5, None, 0.0]


def test_a_list_with_nothing_graded_is_numeric_and_empty_of_values() -> None:
    table = parse_grades("Name,Rating\nA Card,TBD")
    assert table.scale == "number" and table.rows[0].value is None


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("Card,Grade\nA,3", "Name column"),
        ("Name,Stars\nA,3", "grade column"),
        ("Name,Grade\nA,B+\nB,3.0", "mixes letters and numbers"),
        ("Name,Grade\nA,great", "is not a grade"),
        ("Name,Grade\n,3", "no card name"),
    ],
)
def test_malformed_grade_lists_are_refused_with_a_reason(text: str, message: str) -> None:
    with pytest.raises(ShapeError, match=message):
        parse_grades(text)


def test_a_binary_file_is_refused_as_not_a_text_table() -> None:
    with pytest.raises(ShapeError, match="spreadsheet or binary"):
        parse_card_data("PK\x03\x04\x00\x00 xlsx bytes")


def test_a_field_the_csv_module_cannot_read_is_refused_as_not_a_text_table() -> None:
    oversized = "x" * 200_000
    with pytest.raises(ShapeError, match="not a text table"):
        parse_grades(f"Name,Grade,Note\nCard,3,{oversized}")


def test_a_hand_typed_two_column_list_splits_names_with_commas_on_the_last_comma() -> None:
    table = parse_grades('Name,Grade\nEmrakul, the Exigent Doom,4.5\n"Quoted, Card",2')
    assert table.rows == (
        GradeRow("Emrakul, the Exigent Doom", "4.5", 4.5),
        GradeRow("Quoted, Card", "2", 2.0),
    )


@pytest.mark.parametrize("grade", ["45", "-1", "10.5"])
def test_a_numeric_grade_outside_zero_to_ten_is_refused(grade: str) -> None:
    with pytest.raises(ShapeError, match="outside 0 to 10"):
        parse_grades(f"Name,Grade\nA,3\nB,{grade}")


def test_ten_and_zero_are_valid_grades() -> None:
    assert [r.value for r in parse_grades("Name,Grade\nA,10\nB,0").rows] == [10.0, 0.0]


def test_a_list_with_several_grade_columns_is_refused() -> None:
    with pytest.raises(ShapeError, match="several grade columns"):
        parse_grades("Name,Grade,Tier\nA,3,B")


def test_draft_pick_columns_are_detected_when_filled_and_ignored_when_empty() -> None:
    assert parse_card_data(_csv(ROW)).draft_columns_filled
    sealed = [ROW[0], "W", "C", "", "", "", "", *ROW[7:]]
    assert not parse_card_data(_csv(sealed)).draft_columns_filled
    # A real Sealed export counts seen and picked cards but has no average pick positions.
    counted = [ROW[0], "W", "C", "3", "", "1", "", *ROW[7:]]
    assert not parse_card_data(_csv(counted)).draft_columns_filled
    assert not parse_card_data("Name\t# GIH\tGIH WR\nCard\t10\t50.0%").draft_columns_filled
