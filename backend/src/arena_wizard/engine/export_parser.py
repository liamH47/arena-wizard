"""Parse the text Arena's Export button copies: `1 Card Name (SET) 123` per line.

The parser is total: every line becomes a ParsedLine, is skipped as a header or blank, or
becomes an `unparsed` warning. It never raises on input.
"""

from __future__ import annotations

import re

from arena_wizard.domain.pool import ParsedLine, ParseWarning, WarningKind

_LINE = re.compile(r"^(\d+)\s+(.+?)\s+\(([A-Za-z0-9]{2,6})\)\s+(\S+)$")
_HEADERS = {"deck", "sideboard", "commander", "companion", "maybeboard"}
_METADATA = ("about", "name ")


def _is_skippable(text: str) -> bool:
    """Blank lines, section headers, and the `About`/`Name` lines Arena sometimes adds."""
    lowered = text.lower()
    return not text or lowered in _HEADERS or lowered == "about" or lowered.startswith(_METADATA)


def parse_export(text: str) -> tuple[ParsedLine | ParseWarning, ...]:
    """Parse export text into lines and warnings, in input order. Pure.

    Tolerates a byte-order mark, CRLF endings, tabs, non-breaking spaces, and trailing
    whitespace.

    Args:
        text: The pasted export.

    Returns:
        One ParsedLine per card line, one warning per line that is neither a card nor
        skippable.
    """
    results: list[ParsedLine | ParseWarning] = []
    cleaned = text.removeprefix("﻿").replace(" ", " ").replace("\t", " ")
    for line_no, raw in enumerate(cleaned.splitlines(), start=1):
        line = " ".join(raw.split())
        if _is_skippable(line):
            continue
        match = _LINE.match(line)
        if match is None:
            results.append(
                ParseWarning(
                    kind=WarningKind.UNPARSED,
                    message=f"line {line_no} is not an Arena export line",
                    line_no=line_no,
                    raw=raw.strip(),
                )
            )
            continue
        count, name, set_code, number = match.groups()
        results.append(
            ParsedLine(
                line_no=line_no,
                count=int(count),
                name=name,
                set_code=set_code.upper(),
                collector_number=number,
            )
        )
    return tuple(results)
