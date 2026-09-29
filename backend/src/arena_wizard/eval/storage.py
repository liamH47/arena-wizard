"""Reading and writing the committed evaluation files under `backend/eval/`.

The sample and the pre-split counts are committed because 17Lands re-uploads files
without version ids: CI must be able to reproduce the report without downloading
anything. All writes are atomic, deterministic, UTF-8, and LF.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from arena_wizard.domain.stats import CardCounts, PairCounts, Snapshot, SourceRef
from arena_wizard.eval.records import PoolRecord, record_from_json, record_to_json
from arena_wizard.fileio import atomic_write_text

EVAL_DIR = Path(__file__).resolve().parents[3] / "eval"


def write_text(path: Path, text: str) -> None:
    """Write UTF-8 text with LF endings atomically."""
    atomic_write_text(path, text)


def sample_path(root: Path, set_code: str) -> Path:
    """Where a set's sample lives."""
    return root / "pools" / f"{set_code}.sample.jsonl"


def switch_path(root: Path, set_code: str) -> Path:
    """Where a set's switch pools (one pool, two color pairs) live."""
    return root / "pools" / f"{set_code}.switch.jsonl"


def presplit_path(root: Path, set_code: str) -> Path:
    """Where a set's pre-split counts live."""
    return root / "aggregates" / f"{set_code}.presplit.json"


def samples_to_text(records: Iterable[PoolRecord]) -> str:
    """One JSON line per record. Pure."""
    return "".join(record_to_json(r) + "\n" for r in records)


def samples_from_text(text: str) -> tuple[PoolRecord, ...]:
    """Parse `samples_to_text` output. Pure."""
    return tuple(record_from_json(line) for line in text.splitlines() if line.strip())


def snapshot_to_json(snapshot: Snapshot) -> str:
    """Serialize a snapshot's counts and source deterministically. Pure."""
    source = snapshot.source
    document = {
        "set_code": snapshot.set_code,
        "source": {
            "label": source.label,
            "first_day": source.first_day.isoformat() if source.first_day else None,
            "last_day": source.last_day.isoformat() if source.last_day else None,
            "content_sha256": source.content_sha256,
            "games": source.games,
        },
        "cards": {
            name: [c.games_gih, c.wins_gih, c.games_gns, c.wins_gns, c.games_played, c.wins_played]
            for name, c in sorted(snapshot.cards.items())
        },
        "pairs": {code: [p.games, p.wins] for code, p in sorted(snapshot.pairs.items())},
    }
    return json.dumps(document, ensure_ascii=False, indent=1, sort_keys=True) + "\n"


def snapshot_from_json(text: str) -> Snapshot:
    """Parse `snapshot_to_json` output. Pure."""
    raw: dict[str, Any] = json.loads(text)
    s = raw["source"]
    return Snapshot(
        set_code=raw["set_code"],
        source=SourceRef(
            label=s["label"],
            first_day=dt.date.fromisoformat(s["first_day"]) if s["first_day"] else None,
            last_day=dt.date.fromisoformat(s["last_day"]) if s["last_day"] else None,
            content_sha256=s["content_sha256"],
            games=s["games"],
        ),
        cards={name: CardCounts(*v) for name, v in raw["cards"].items()},
        pairs={code: PairCounts(*v) for code, v in raw["pairs"].items()},
    )


def read_json(path: Path) -> Any:
    """Parse a JSON file, or return None when it does not exist."""
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def json_text(value: Mapping[str, Any] | list[Any]) -> str:
    """Deterministic, readable JSON with a trailing newline. Pure."""
    return json.dumps(value, ensure_ascii=False, indent=1, sort_keys=True) + "\n"


def reports_match(a: Any, b: Any) -> bool:
    """True when two reports agree; rounded numbers may differ by one unit in the fourth place.

    The unit of slack absorbs a last-bit floating-point difference between platforms that
    lands on a rounding boundary. Booleans and numbers never match each other.
    """
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    if isinstance(a, float) or isinstance(b, float):
        numbers = isinstance(a, int | float) and isinstance(b, int | float)
        return numbers and abs(round(a * 10_000) - round(b * 10_000)) <= 1
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(reports_match(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(reports_match(x, y) for x, y in zip(a, b, strict=True))
    return bool(a == b)
