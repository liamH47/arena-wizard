"""Invariants of the committed evaluation set: no pool the engine is judged on can have
contributed to the statistics it is judged with."""

from __future__ import annotations

import datetime as dt
import hashlib
from pathlib import Path
from typing import Any

import pytest

from arena_wizard.eval.storage import (
    EVAL_DIR,
    presplit_path,
    read_json,
    sample_path,
    samples_from_text,
    snapshot_from_json,
    switch_path,
)

PINS: dict[str, Any] = read_json(EVAL_DIR / "pins.json") or {}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_there_are_pinned_sets() -> None:
    assert set(PINS) >= {"SOS", "HOB"}


@pytest.mark.parametrize("code", sorted(PINS))
def test_the_committed_files_match_their_pins(code: str) -> None:
    pin = PINS[code]
    assert _sha256(sample_path(EVAL_DIR, code)) == pin["sample_sha256"]
    assert _sha256(switch_path(EVAL_DIR, code)) == pin["switch_sha256"]
    assert _sha256(presplit_path(EVAL_DIR, code)) == pin["presplit_sha256"]


@pytest.mark.parametrize("code", sorted(PINS))
def test_every_evaluated_pool_started_after_the_split_day(code: str) -> None:
    split_day = dt.date.fromisoformat(PINS[code]["split_day"])
    for path, size in (
        (sample_path(EVAL_DIR, code), PINS[code]["sample_size"]),
        (switch_path(EVAL_DIR, code), PINS[code]["switch_size"]),
    ):
        records = samples_from_text(path.read_text(encoding="utf-8"))
        assert len(records) == size
        assert len({r.draft_id for r in records}) == size
        early = [r.draft_id for r in records if r.first_day <= split_day]
        assert early == [], f"{path.name}: pools on or before {split_day}"


@pytest.mark.parametrize("code", sorted(PINS))
def test_the_statistics_end_on_or_before_the_split_day(code: str) -> None:
    split_day = dt.date.fromisoformat(PINS[code]["split_day"])
    snapshot = snapshot_from_json(presplit_path(EVAL_DIR, code).read_text(encoding="utf-8"))
    assert snapshot.set_code == code
    assert snapshot.source.last_day is not None and snapshot.source.last_day <= split_day
    assert snapshot.source.content_sha256 == PINS[code]["sha256"]
    assert 0 < snapshot.source.games < PINS[code]["games"]
