"""The `paste` and `pastes` commands: data a person brings in by hand (decisions 0005, 0007).

A paste is parsed and checked completely before anything is written, so a refused paste
never replaces a good one. Nothing here opens a network connection: a paste's link is a
label, never fetched.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from arena_wizard.catalog import load_packaged_card_table
from arena_wizard.domain.scoring import load_scoring_config
from arena_wizard.domain.sets import EventType, Format, SetConfig
from arena_wizard.engine.values import spell_rarities
from arena_wizard.etl.cache_paths import counts_path
from arena_wizard.pastes.check import PasteRefused, check_card_data, check_grades
from arena_wizard.pastes.names import name_index
from arena_wizard.pastes.parsers import (
    PARSER_VERSION,
    CardDataRow,
    GradeRow,
    ShapeError,
    parse_card_data,
    parse_grades,
)
from arena_wizard.pastes.sources import CARD_DATA, GRADES, UnknownSource, source_for
from arena_wizard.pastes.store import (
    PasteKey,
    StoredPaste,
    delete_paste,
    from_json,
    read_pastes,
    source_label,
    write_paste,
)

Echo = Callable[[str], None]
MAX_BYTES = 5_000_000
PUBLIC_EVENT_TYPES = (EventType.SEALED, EventType.PREMIER_DRAFT)
"""The public files the engine reads; a paste of the same data is refused once one is here."""


@dataclass(frozen=True, slots=True)
class PasteRequest:
    """Everything the person typed for one paste."""

    set_code: str
    dataset: str
    source_id: str
    event_type: EventType | None
    copied_on: dt.date | None
    published_on: dt.date | None
    url: str | None
    replace: bool


def covered_event_types(config: SetConfig, cache: Path, today: dt.date) -> frozenset[EventType]:
    """Event types whose public file is cached and past the embargo (0005, rule 4)."""
    if today < config.embargo_until:
        return frozenset()
    return frozenset(e for e in PUBLIC_EVENT_TYPES if counts_path(cache, config.code, e).is_file())


def text_sha256(text: str) -> str:
    """Hash of the decoded text with the byte-order mark and CR characters removed."""
    normalized = text.lstrip("﻿").replace("\r", "")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


class _Refused(Exception):
    """A paste refused before anything was written."""


def _dates(request: PasteRequest, config: SetConfig, today: dt.date) -> dt.date:
    copied_on = request.copied_on or today
    if copied_on > today:
        raise _Refused(f"--copied-on {copied_on} is after today ({today}, UTC)")
    if request.published_on is not None and request.published_on > today:
        raise _Refused(f"--published-on {request.published_on} is after today ({today}, UTC)")
    if request.dataset == CARD_DATA and copied_on < config.arena_release_date:
        raise _Refused(
            f"--copied-on {copied_on} is before {config.code} reached Arena "
            f"({config.arena_release_date}), so it cannot be {config.code} card data"
        )
    return copied_on


def _check_request(request: PasteRequest) -> None:
    source = source_for(request.source_id)
    if source.dataset != request.dataset:
        raise _Refused(f"{request.source_id} provides {source.dataset}, not {request.dataset}")
    if request.dataset == CARD_DATA and request.event_type is None:
        raise _Refused(
            "card data needs --event-type (ArenaDirect_Sealed, Sealed, or PremierDraft); it "
            "has no default, so draft data is never labelled as sealed"
        )
    if request.dataset == GRADES and request.event_type is not None:
        raise _Refused("grades take no --event-type")


def paste(
    request: PasteRequest,
    data: bytes,
    config: SetConfig,
    data_dir: Path,
    cache: Path,
    today: dt.date,
    decode: Callable[[bytes], str],
    echo: Echo,
) -> int:
    """Parse, check, and store one paste. Nothing is written unless every check passes.

    Args:
        request: What the person typed.
        data: The pasted bytes, from a file or stdin.
        config: The set's configuration.
        data_dir: The private data directory.
        cache: The download cache, to see which public files the engine already reads.
        today: The UTC day, which is the paste's key.
        decode: Turns bytes into text whatever tool saved them.
        echo: Where messages go.

    Returns:
        0 when stored or unchanged, 1 when refused.
    """
    try:
        _check_request(request)
        copied_on = _dates(request, config, today)
        if len(data) > MAX_BYTES:
            raise _Refused(f"the paste is over {MAX_BYTES:,} bytes; export one set's table")
        if request.event_type in covered_event_types(config, cache, today):
            raise _Refused(
                f"the 17Lands public {request.event_type} file for {config.code} is already "
                "cached, and permitted automated data replaces pastes (decision 0005, rule 4)"
            )
        text = decode(data)
        table = load_packaged_card_table(config.code)
        index = name_index(table.cards)
        spells = frozenset(spell_rarities(table.cards))
        card_rows: tuple[CardDataRow, ...] = ()
        grade_rows: tuple[GradeRow, ...] = ()
        warnings: tuple[str, ...] = ()
        if request.event_type is not None:
            parsed = parse_card_data(text)
            cards = check_card_data(parsed, request.event_type, index, spells, config.code)
            columns, unknown, card_rows, warnings = (
                parsed.columns,
                cards.unknown,
                cards.rows,
                cards.warnings,
            )
        else:
            grade_table = parse_grades(text)
            coverage = load_scoring_config(Format.BO1_SEALED, config.code).event
            grades = check_grades(
                grade_table, index, spells, config.code, coverage.min_grade_coverage
            )
            columns, unknown, grade_rows = (grade_table.column,), grades.unknown, grades.rows
    except (UnknownSource, ShapeError, PasteRefused, _Refused) as error:
        echo(f"Refused, nothing stored: {error}.")
        return 1
    sha = text_sha256(text)
    key = PasteKey(config.code, request.dataset, request.event_type, request.source_id, today)
    stored, _ = read_pastes(data_dir, config.code)
    twin = next(
        (p for p in stored if p.text_sha256 == sha and p.key.source_id != request.source_id),
        None,
    )
    if twin is not None:
        echo(
            f"Refused, nothing stored: this is the same text as the {twin.label} paste from "
            f"{twin.key.import_day}; one source's grades counted twice would double its weight."
        )
        return 1
    new = StoredPaste(
        key=key,
        label=source_for(request.source_id).label,
        url=request.url,
        copied_on=copied_on,
        published_on=request.published_on,
        columns=columns,
        text_sha256=sha,
        parser_version=PARSER_VERSION,
        card_rows=card_rows,
        grade_rows=grade_rows,
    )
    path = key.path(data_dir)
    old = from_json(path.read_text(encoding="utf-8")) if path.is_file() else None
    if old is not None and new.row_count * 2 < old.row_count and not request.replace:
        echo(
            f"Refused, nothing stored: today's {old.label} paste has {old.row_count} rows and "
            f"this one has {new.row_count}. Pass --replace if the smaller paste is right."
        )
        return 1
    if not write_paste(data_dir, new):
        echo("Identical to today's stored paste from this source; nothing changed.")
        return 0
    verb = "Replaced today's paste" if old is not None else "Stored"
    echo(
        f"{verb}: {source_label(new)}, {new.row_count} rows"
        + (f" (was {old.row_count})" if old is not None else "")
        + f". Kept privately in {data_dir}; never committed. sha256 {sha[:16]}."
    )
    if request.copied_on is None:
        echo(
            f"Copied-on defaulted to today, {today} UTC; pass --copied-on if you copied it earlier."
        )
    if unknown:
        shown = ", ".join(repr(n) for n in unknown[:5])
        more = f", and {len(unknown) - 5} more" if len(unknown) > 5 else ""
        echo(f"{len(unknown)} names are not {config.code} cards and were skipped: {shown}{more}.")
    for warning in warnings:
        echo(warning)
    return 0


def list_pastes(set_code: str, data_dir: Path, echo: Echo) -> int:
    """Print every stored paste for a set, newest last, and any that must be pasted again."""
    pastes, stale = read_pastes(data_dir, set_code)
    echo(f"{set_code} pastes, private, in {data_dir}:")
    if not pastes and not stale:
        echo("  none")
    for p in pastes:
        kind = p.key.event_type.value if p.key.event_type else "grades"
        echo(
            f"  {p.key.dataset}/{kind}/{p.key.source_id}/{p.key.import_day}  {p.label}, copied "
            f"{p.copied_on}, {p.row_count} rows"
        )
    for problem in stale:
        echo(f"  {problem}")
    return 0


def delete(set_code: str, key_text: str, data_dir: Path, echo: Echo) -> int:
    """Delete one paste named as dataset/kind/source/day, as `pastes` prints it."""
    parts = key_text.strip("/").split("/")
    try:
        dataset, kind, source_id, day = parts
        key = PasteKey(
            set_code,
            dataset,
            None if kind == GRADES else EventType(kind),
            source_for(source_id).id,
            dt.date.fromisoformat(day),
        )
    except (ValueError, UnknownSource):
        echo(
            f"Not a paste key: {key_text!r}. Copy one from `arena-wizard pastes --set {set_code}`."
        )
        return 1
    if not delete_paste(data_dir, key):
        echo(f"No stored paste {key_text}.")
        return 1
    echo(f"Deleted {key_text}.")
    return 0
