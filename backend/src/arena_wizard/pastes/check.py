"""Checks a paste must pass before it is stored (decision 0007). Pure.

Everything is checked before anything is written, so a refused paste never replaces a
good one. Each refusal says what to do about it.
"""

from __future__ import annotations

import dataclasses
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from arena_wizard.domain.sets import EventType
from arena_wizard.pastes.names import resolve
from arena_wizard.pastes.parsers import CardDataRow, CardDataTable, GradeRow, GradeTable

MIN_MATCHED_ROWS = 0.9
"""Below this share of recognised names, the page was set to another set, or the text was
garbled on the way in."""
MIN_CARD_COVERAGE = 0.8
"""A card-data export covering fewer of the set's spells had a Color or Rarity filter on."""
CARD_DATA_EVENT_TYPES = (
    EventType.ARENA_DIRECT_SEALED,
    EventType.SEALED,
    EventType.PREMIER_DRAFT,
)
ENCODING_DAMAGE = ("?", "�")


class PasteRefused(ValueError):
    """The paste fails a check; nothing was stored."""


@dataclass(frozen=True, slots=True)
class Checked[Row]:
    """The rows that passed, renamed to 17Lands (front-face) names, and the warnings."""

    rows: tuple[Row, ...]
    unknown: tuple[str, ...]
    warnings: tuple[str, ...]


def _resolve_names[Row: (CardDataRow, GradeRow)](
    rows: Sequence[Row], index: Mapping[str, str], set_code: str
) -> tuple[list[Row], list[str]]:
    """Rename rows to front-face names; refuse garbled or wrong-set text."""
    matched: list[Row] = []
    unknown: list[str] = []
    for row in rows:
        front = resolve(row.name, index)
        if front is None:
            unknown.append(row.name)
        else:
            matched.append(dataclasses.replace(row, name=front))
    damaged = [name for name in unknown if any(mark in name for mark in ENCODING_DAMAGE)]
    if damaged:
        raise PasteRefused(
            f"names were damaged on the way in ({damaged[0]!r}); upload the exported file "
            "instead of pasting or piping it"
        )
    if rows and len(matched) < MIN_MATCHED_ROWS * len(rows):
        raise PasteRefused(
            f"{len(unknown)} of {len(rows)} names are not {set_code} cards; the page was "
            f"probably set to another expansion"
        )
    return matched, unknown


def _deduplicate[Row: (CardDataRow, GradeRow)](rows: list[Row]) -> list[Row]:
    """Drop exact repeats; refuse a card listed twice with different numbers."""
    seen: dict[str, Row] = {}
    for row in rows:
        earlier = seen.get(row.name)
        if earlier is None:
            seen[row.name] = row
        elif earlier != row:
            raise PasteRefused(f"{row.name} appears twice with different values; keep one row")
    return sorted(seen.values(), key=lambda r: r.name)


def check_card_data(
    table: CardDataTable,
    event_type: EventType,
    index: Mapping[str, str],
    spells: frozenset[str],
    set_code: str,
) -> Checked[CardDataRow]:
    """Check a 17Lands card-data export for one set and event type.

    Raises:
        PasteRefused: Wrong set, filtered, no games, draft columns on a sealed paste, or a
            card listed twice with different numbers.
    """
    if event_type not in CARD_DATA_EVENT_TYPES:
        raise PasteRefused("card data must be Arena Direct Sealed, Sealed, or Premier Draft")
    if event_type is not EventType.PREMIER_DRAFT and table.draft_columns_filled:
        raise PasteRefused(
            f"the export has draft pick columns filled in (# Seen, ALSA, # Picked, ATA), so it "
            f"is draft data, not {event_type.value}; pass --event-type PremierDraft"
        )
    matched, unknown = _resolve_names(table.rows, index, set_code)
    rows = _deduplicate(matched)
    covered = {r.name for r in rows} & spells
    if len(covered) < MIN_CARD_COVERAGE * len(spells):
        raise PasteRefused(
            f"the export covers {len(covered)} of {set_code}'s {len(spells)} spells; clear the "
            "Color and Rarity filters on the 17Lands page and export again"
        )
    if not any(r.games_gih and r.gih_wr is not None for r in rows):
        raise PasteRefused(
            "no card has any game-in-hand games. 17Lands shows no card win rates for regular "
            "Sealed (checked 2026-09-28); copy Arena Direct Sealed or Premier Draft instead"
        )
    warnings = []
    if not {"# GNS", "GNS WR"} <= set(table.columns):
        warnings.append(
            'No "Not Seen" columns in this paste, so values use win rate in hand only; tick '
            "Not Seen on 17Lands to add improvement when drawn."
        )
    return Checked(tuple(rows), tuple(unknown), tuple(warnings))


def check_grades(
    table: GradeTable,
    index: Mapping[str, str],
    spells: frozenset[str],
    set_code: str,
    min_coverage: float,
) -> Checked[GradeRow]:
    """Check a grade list for one set.

    Raises:
        PasteRefused: Wrong set, too few spells graded, every grade equal, or a card
            graded twice differently.
    """
    matched, unknown = _resolve_names(table.rows, index, set_code)
    rows = _deduplicate(matched)
    graded = {r.name: r.value for r in rows if r.value is not None and r.name in spells}
    if len(graded) < min_coverage * len(spells):
        raise PasteRefused(
            f"the list grades {len(graded)} of {set_code}'s {len(spells)} spells; a source "
            f"must grade at least {min_coverage:.0%} so its grades can be put on one scale "
            "with the others"
        )
    if len(graded) < 2 or statistics.pstdev(graded.values()) == 0:
        raise PasteRefused("every grade in the list is the same, so it cannot rank cards")
    return Checked(tuple(rows), tuple(unknown), ())
