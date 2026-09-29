"""The private paste store: one file per key, outside every repository (decision 0007).

The key is (set, dataset, event type, source id, UTC import day), and the file path is the
key, so decision 0005's "at most one paste per source, set, dataset, and UTC day" holds by
construction: pasting again the same day replaces that day's file atomically. Files are
deterministic JSON, so an identical re-paste is detected and nothing is rewritten.

Every function takes the data directory as a required argument; only `cli.main` resolves
it, so a test cannot touch the owner's real data by forgetting an argument.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from arena_wizard.datadir import PRIVATE_MARKER
from arena_wizard.domain.sets import EventType
from arena_wizard.domain.stats import CardCounts, Snapshot, SourceRef
from arena_wizard.fileio import atomic_write_text
from arena_wizard.pastes.parsers import PARSER_VERSION, CardDataRow, GradeRow
from arena_wizard.pastes.sources import CARD_DATA, GRADES, source_for

FORMAT_VERSION = 1
_DAY_FILE = re.compile(r"\d{4}-\d{2}-\d{2}\.json")


@dataclass(frozen=True, slots=True)
class PasteKey:
    """Decision 0005's unique key. `event_type` is None for grades."""

    set_code: str
    dataset: str
    event_type: EventType | None
    source_id: str
    import_day: dt.date

    def path(self, data_dir: Path) -> Path:
        """Where this paste lives under the data directory."""
        kind = self.event_type.value if self.event_type else GRADES
        return (
            data_dir
            / "pastes"
            / self.set_code
            / self.dataset
            / kind
            / self.source_id
            / f"{self.import_day.isoformat()}.json"
        )


@dataclass(frozen=True, slots=True)
class StoredPaste:
    """A checked paste: where it came from, when, and its parsed rows. No raw text."""

    key: PasteKey
    label: str
    url: str | None
    copied_on: dt.date
    published_on: dt.date | None
    columns: tuple[str, ...]
    text_sha256: str
    parser_version: int
    card_rows: tuple[CardDataRow, ...] = ()
    grade_rows: tuple[GradeRow, ...] = ()

    @property
    def row_count(self) -> int:
        """Rows stored, whichever dataset."""
        return len(self.card_rows) or len(self.grade_rows)


class StaleFile(ValueError):
    """A stored file from an older parser or format; it must be pasted again."""


def _date(value: str | None) -> dt.date | None:
    return dt.date.fromisoformat(value) if value else None


def to_json(paste: StoredPaste) -> str:
    """Serialize deterministically: sorted keys, one trailing newline. Pure."""
    document: dict[str, Any] = {
        "kind": PRIVATE_MARKER,
        "format_version": FORMAT_VERSION,
        "parser_version": paste.parser_version,
        "set_code": paste.key.set_code,
        "dataset": paste.key.dataset,
        "event_type": paste.key.event_type.value if paste.key.event_type else None,
        "source_id": paste.key.source_id,
        "import_day": paste.key.import_day.isoformat(),
        "label": paste.label,
        "url": paste.url,
        "copied_on": paste.copied_on.isoformat(),
        "published_on": paste.published_on.isoformat() if paste.published_on else None,
        "columns": list(paste.columns),
        "text_sha256": paste.text_sha256,
        "card_rows": [
            [r.name, r.color, r.rarity, r.games_gih, r.gih_wr, r.games_gns, r.gns_wr]
            for r in paste.card_rows
        ],
        "grade_rows": [[r.name, r.raw, r.value] for r in paste.grade_rows],
    }
    return json.dumps(document, ensure_ascii=False, indent=1, sort_keys=True) + "\n"


def from_json(text: str) -> StoredPaste:
    """Parse a stored paste. Pure.

    Raises:
        StaleFile: The file comes from an older format or parser version.
    """
    raw = json.loads(text)
    if raw.get("format_version") != FORMAT_VERSION or raw.get("parser_version") != PARSER_VERSION:
        raise StaleFile(
            f"{raw.get('label')} from {raw.get('import_day')} was stored by an older version; "
            "paste it again"
        )
    event = raw["event_type"]
    return StoredPaste(
        key=PasteKey(
            raw["set_code"],
            raw["dataset"],
            EventType(event) if event else None,
            raw["source_id"],
            dt.date.fromisoformat(raw["import_day"]),
        ),
        label=raw["label"],
        url=raw["url"],
        copied_on=dt.date.fromisoformat(raw["copied_on"]),
        published_on=_date(raw["published_on"]),
        columns=tuple(raw["columns"]),
        text_sha256=raw["text_sha256"],
        parser_version=raw["parser_version"],
        card_rows=tuple(CardDataRow(*row) for row in raw["card_rows"]),
        grade_rows=tuple(GradeRow(*row) for row in raw["grade_rows"]),
    )


def write_paste(data_dir: Path, paste: StoredPaste) -> bool:
    """Store a paste under its key, replacing that day's file. Idempotent.

    Returns:
        False when an identical file was already stored and nothing was written.
    """
    path = paste.key.path(data_dir)
    text = to_json(paste)
    if path.is_file() and path.read_text(encoding="utf-8") == text:
        return False
    atomic_write_text(path, text)
    return True


def read_pastes(data_dir: Path, set_code: str) -> tuple[tuple[StoredPaste, ...], tuple[str, ...]]:
    """Every stored paste for a set, in key order, and a message for each stale file."""
    root = data_dir / "pastes" / set_code
    pastes: list[StoredPaste] = []
    problems: list[str] = []
    files = sorted(p for p in root.rglob("*.json") if _DAY_FILE.fullmatch(p.name))
    for path in files:
        try:
            pastes.append(from_json(path.read_text(encoding="utf-8")))
        except StaleFile as error:
            problems.append(str(error))
    return tuple(pastes), tuple(problems)


def delete_paste(data_dir: Path, key: PasteKey) -> bool:
    """Remove one paste; False when there was none."""
    path = key.path(data_dir)
    if not path.is_file():
        return False
    path.unlink()
    return True


def _latest(pastes: Iterable[StoredPaste]) -> StoredPaste | None:
    """The most recent by import day, then copy day; source id breaks ties."""
    ordered = sorted(pastes, key=lambda p: (p.key.import_day, p.copied_on, p.key.source_id))
    return ordered[-1] if ordered else None


def latest_card_data(
    pastes: Sequence[StoredPaste], event_type: EventType, covered: frozenset[EventType]
) -> StoredPaste | None:
    """The newest card-data paste of one event type, unless automated data covers it."""
    if event_type in covered:
        return None
    return _latest(
        p for p in pastes if p.key.dataset == CARD_DATA and p.key.event_type is event_type
    )


def latest_grades(pastes: Sequence[StoredPaste]) -> tuple[StoredPaste, ...]:
    """The newest grade paste for each source, in source-id order."""
    by_source: dict[str, list[StoredPaste]] = {}
    for paste in pastes:
        if paste.key.dataset == GRADES:
            by_source.setdefault(paste.key.source_id, []).append(paste)
    return tuple(p for sid in sorted(by_source) if (p := _latest(by_source[sid])) is not None)


def to_snapshot(paste: StoredPaste) -> Snapshot:
    """Counts from a card-data paste. A count whose rate is blank is left out, never 0 wins."""
    cards: dict[str, CardCounts] = {}
    for row in paste.card_rows:
        if not row.games_gih or row.gih_wr is None:
            continue
        games_gns = wins_gns = 0
        if row.games_gns and row.gns_wr is not None:
            games_gns, wins_gns = row.games_gns, round(row.gns_wr * row.games_gns)
        cards[row.name] = CardCounts(
            games_gih=row.games_gih,
            wins_gih=round(row.gih_wr * row.games_gih),
            games_gns=games_gns,
            wins_gns=wins_gns,
        )
    source = SourceRef(paste.label, None, None, paste.text_sha256, 0)
    return Snapshot(paste.key.set_code, source, cards, {})


EVENT_NAMES = {
    EventType.ARENA_DIRECT_SEALED: "Arena Direct Sealed",
    EventType.SEALED: "Sealed",
    EventType.PREMIER_DRAFT: "Premier Draft",
    EventType.TRAD_SEALED: "Traditional Sealed",
}
LAYER_NAMES = {
    EventType.ARENA_DIRECT_SEALED: "Arena Direct",
    EventType.SEALED: "Sealed paste",
    EventType.PREMIER_DRAFT: "draft data",
    EventType.TRAD_SEALED: "Traditional Sealed paste",
}
"""Short names for a value's weight breakdown, e.g. "Arena Direct 60%, draft data 30%"."""


def source_label(paste: StoredPaste) -> str:
    """How builds name a paste: source, event type, and the day it was copied."""
    kind = f", {EVENT_NAMES[paste.key.event_type]}" if paste.key.event_type else ""
    registered = source_for(paste.key.source_id).label
    return f"{registered}{kind}, pasted by hand, copied {paste.copied_on.isoformat()}"
