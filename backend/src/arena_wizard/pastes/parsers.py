"""Parse text a person exported or copied by hand. Pure: no I/O, no network.

Two layouts:

- The 17Lands card-data export, either "Download as CSV" (a byte-order mark, every cell in
  double quotes, embedded quotes not escaped, no trailing newline) or "Copy to clipboard"
  (tab-separated, unquoted). Columns are whatever the person ticked, so they are found by
  header name. Layout read from the site's static bundle by the data-source steward,
  2026-09-29 (decision 0007).
- A grade list: a `Name` column and one grade column, comma- or tab-separated. Covers a
  Limited Level-Ups "Download CSV" (Name, Tier, ...), a hand-typed review transcription,
  and the group's own grades.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Sequence
from dataclasses import dataclass

PARSER_VERSION = 1
"""Stored with every paste; a paste from an older version must be pasted again."""
REQUIRED_CARD_COLUMNS = ("Name", "# GIH", "GIH WR")
DRAFT_COLUMNS = ("ALSA", "ATA")
"""Average pick positions: filled only for drafts. A Sealed export leaves them blank but
puts small counts in # Seen and # Picked (seen in an FRA export, 2026-10-06)."""
GRADE_COLUMNS = ("Grade", "Rating", "Tier", "Score")
LETTER_GRADES = ("F", "D-", "D", "D+", "C-", "C", "C+", "B-", "B", "B+", "A-", "A", "A+")
"""17Lands tier letters, worst first. `SB` (sideboard) ranks one step below `F`."""
UNGRADED = ("", "TBD", "-", "N/A")


class ShapeError(ValueError):
    """The text is not in a layout this parser understands; the message says how to fix it."""


@dataclass(frozen=True, slots=True)
class CardDataRow:
    """One card's row from a 17Lands card-data export. Missing cells are None."""

    name: str
    color: str
    rarity: str | None
    games_gih: int | None
    gih_wr: float | None
    games_gns: int | None
    gns_wr: float | None


@dataclass(frozen=True, slots=True)
class CardDataTable:
    """A parsed card-data export and the columns it carried."""

    columns: tuple[str, ...]
    rows: tuple[CardDataRow, ...]
    draft_columns_filled: bool


@dataclass(frozen=True, slots=True)
class GradeRow:
    """One card's grade as written, and its position on an ordered scale (higher is better)."""

    name: str
    raw: str
    value: float | None


@dataclass(frozen=True, slots=True)
class GradeTable:
    """A parsed grade list. `scale` is "letter" or "number"."""

    column: str
    scale: str
    rows: tuple[GradeRow, ...]


def _lines(text: str) -> list[str]:
    """Split into non-blank lines after dropping a byte-order mark and CR characters."""
    return [line for line in text.lstrip("﻿").replace("\r", "").split("\n") if line.strip()]


def _split(line: str, mode: str, width: int = 0) -> list[str]:
    """Split one line into cells.

    `mode` is "tab" for clipboard text, "quoted" for 17Lands' CSV, which quotes every cell
    and does not escape quotes inside them (so it is split on `","`, which survives commas
    inside names), or "csv" for a file re-saved by a spreadsheet.
    """
    if mode == "tab":
        return [cell.strip() for cell in line.split("\t")]
    stripped = line.strip()
    if mode == "quoted" and len(stripped) >= 2 and stripped[0] == stripped[-1] == '"':
        return [cell.strip() for cell in stripped[1:-1].split('","')]
    if width == 2 and not stripped.startswith('"'):
        # A hand-typed "name,grade" list: names may contain commas, grades never do.
        return [cell.strip() for cell in stripped.rsplit(",", 1)]
    try:
        return [cell.strip() for cell in next(csv.reader(io.StringIO(stripped)))]
    except csv.Error:
        raise ShapeError("this is not a text table; export CSV or copy the table") from None


def _table(text: str) -> tuple[list[str], list[list[str]]]:
    """Header and rows. The header line decides the layout for every line after it."""
    if "\x00" in text:
        raise ShapeError("this looks like a spreadsheet or binary file, not a text table")
    lines = _lines(text)
    if not lines:
        raise ShapeError("the paste is empty")
    first = lines[0].strip()
    mode = "tab" if "\t" in first else "quoted" if first.startswith('"') else "csv"
    header = _split(first, mode)
    rows = []
    for number, line in enumerate(lines[1:], start=2):
        cells = _split(line, mode, len(header))
        if len(cells) != len(header):
            raise ShapeError(
                f"line {number} has {len(cells)} cells but the header has {len(header)}: "
                f"{line[:80]}"
            )
        rows.append(cells)
    return header, rows


def _count(cell: str, column: str, name: str) -> int | None:
    if cell == "":
        return None
    try:
        return int(cell.replace(",", ""))
    except ValueError:
        raise ShapeError(f"{name}: {column} should be a whole number, got {cell!r}") from None


def _percent(cell: str, column: str, name: str) -> float | None:
    if cell == "" or cell == "NaN%":
        return None
    try:
        return float(cell.removesuffix("%")) / 100
    except ValueError:
        raise ShapeError(f"{name}: {column} should look like 55.2%, got {cell!r}") from None


def parse_card_data(text: str) -> CardDataTable:
    """Parse a 17Lands card-data export (CSV download or clipboard copy). Pure.

    Raises:
        ShapeError: No header row, a required column missing, a row of the wrong width, a
            cell that is not a number where one belongs, or binary content.
    """
    header, rows = _table(text)
    missing = [c for c in REQUIRED_CARD_COLUMNS if c not in header]
    if missing:
        raise ShapeError(
            f"the export has no {', '.join(missing)} column. On 17Lands' card data page, "
            "switch to the Table view, tick Ever in Hand (and Not Seen), then export again"
        )
    at = {column: i for i, column in enumerate(header)}

    def cell(row: Sequence[str], column: str) -> str:
        return row[at[column]] if column in at else ""

    parsed = []
    for row in rows:
        name = cell(row, "Name")
        if not name:
            raise ShapeError("a row has no card name")
        parsed.append(
            CardDataRow(
                name=name,
                color=cell(row, "Color"),
                rarity=cell(row, "Rarity") or None,
                games_gih=_count(cell(row, "# GIH"), "# GIH", name),
                gih_wr=_percent(cell(row, "GIH WR"), "GIH WR", name),
                games_gns=_count(cell(row, "# GNS"), "# GNS", name),
                gns_wr=_percent(cell(row, "GNS WR"), "GNS WR", name),
            )
        )
    filled = any(cell(row, column) for row in rows for column in DRAFT_COLUMNS)
    return CardDataTable(columns=tuple(header), rows=tuple(parsed), draft_columns_filled=filled)


def _grade_value(raw: str, scale: str) -> float | None:
    """A grade's position on its scale, or None when it is ungraded."""
    upper = raw.strip().upper()
    if upper in UNGRADED:
        return None
    if scale == "letter":
        return -1.0 if upper == "SB" else float(LETTER_GRADES.index(upper))
    value = float(upper)
    if not 0 <= value <= 10:
        raise ShapeError(f"{raw!r} is outside 0 to 10; is a decimal point missing?")
    return value


def _scale_of(raws: Sequence[str]) -> str:
    """Decide whether a grade column holds letters or numbers; a mix is refused."""
    kinds = set()
    for raw in raws:
        upper = raw.strip().upper()
        if upper in UNGRADED:
            continue
        if upper in LETTER_GRADES or upper == "SB":
            kinds.add("letter")
            continue
        try:
            float(upper)
        except ValueError:
            raise ShapeError(
                f"{raw!r} is not a grade: use numbers, or letters A+ to F, SB, or TBD"
            ) from None
        kinds.add("number")
    if len(kinds) > 1:
        raise ShapeError("the grade column mixes letters and numbers; use one or the other")
    return kinds.pop() if kinds else "number"


def parse_grades(text: str) -> GradeTable:
    """Parse a grade list with a Name column and one grade column. Pure.

    Raises:
        ShapeError: No Name or grade column, several grade columns, a row of the wrong
            width, a value that is not a grade or is outside 0 to 10, or letters and numbers
            mixed in one column.
    """
    header, rows = _table(text)
    folded = {column.casefold(): i for i, column in enumerate(header)}
    if "name" not in folded:
        raise ShapeError("the list needs a Name column")
    present = [c for c in GRADE_COLUMNS if c.casefold() in folded]
    if not present:
        raise ShapeError(f"the list needs a grade column named one of {', '.join(GRADE_COLUMNS)}")
    if len(present) > 1:
        raise ShapeError(f"the list has several grade columns ({', '.join(present)}); keep one")
    grade = present[0]
    name_at, grade_at = folded["name"], folded[grade.casefold()]
    raws = [row[grade_at] for row in rows]
    scale = _scale_of(raws)
    parsed = []
    for row in rows:
        if not row[name_at]:
            raise ShapeError("a row has no card name")
        parsed.append(GradeRow(row[name_at], row[grade_at], _grade_value(row[grade_at], scale)))
    return GradeTable(column=header[grade_at], scale=scale, rows=tuple(parsed))
