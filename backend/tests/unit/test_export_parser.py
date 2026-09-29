from __future__ import annotations

from arena_wizard.domain.pool import ParsedLine, ParseWarning, WarningKind
from arena_wizard.engine.export_parser import parse_export


def test_a_standard_export_parses_every_line_in_order() -> None:
    text = "Deck\n2 Last Gasp (SOS) 98\n1 Abigale, Poet Laureate (SOS) 170\n"
    assert parse_export(text) == (
        ParsedLine(2, 2, "Last Gasp", "SOS", "98"),
        ParsedLine(3, 1, "Abigale, Poet Laureate", "SOS", "170"),
    )


def test_headers_blank_lines_and_arena_metadata_are_skipped() -> None:
    text = "About\nName Sealed Pool\n\nDeck\n1 Plains (SOS) 272\n\nSideboard\n1 Erode (SOS) 7\n"
    assert [item.name for item in parse_export(text) if isinstance(item, ParsedLine)] == [
        "Plains",
        "Erode",
    ]


def test_a_byte_order_mark_crlf_tabs_and_non_breaking_spaces_are_tolerated() -> None:
    text = "﻿1 Last Gasp\t(SOS) 98\r\n1 Erode (sos) 7  \r\n"
    assert parse_export(text) == (
        ParsedLine(1, 1, "Last Gasp", "SOS", "98"),
        ParsedLine(2, 1, "Erode", "SOS", "7"),
    )


def test_split_names_and_lettered_collector_numbers_parse() -> None:
    text = "1 Library of Alexandria (SPG) 158a\n1 Elite Interceptor // Rejoinder (SOS) 12\n"
    names = [item.name for item in parse_export(text) if isinstance(item, ParsedLine)]
    assert names == ["Library of Alexandria", "Elite Interceptor // Rejoinder"]


def test_a_line_that_is_not_an_export_line_becomes_a_warning_not_an_error() -> None:
    (item,) = parse_export("Last Gasp x2\n")
    assert isinstance(item, ParseWarning)
    assert item.kind is WarningKind.UNPARSED
    assert item.line_no == 1 and item.raw == "Last Gasp x2"


def test_empty_input_is_empty() -> None:
    assert parse_export("") == ()
