from __future__ import annotations

import datetime as dt
from pathlib import Path

from arena_wizard.domain.stats import CardCounts, PairCounts, Snapshot, SourceRef
from arena_wizard.eval.records import BuildRecord, PoolRecord
from arena_wizard.eval.storage import (
    json_text,
    presplit_path,
    read_json,
    reports_match,
    sample_path,
    samples_from_text,
    samples_to_text,
    snapshot_from_json,
    snapshot_to_json,
    switch_path,
    write_text,
)

RECORD = PoolRecord(
    draft_id="d1",
    first_day=dt.date(2026, 4, 23),
    pool={"Dáin": 1, "Alpha": 2},
    builds=(BuildRecord(0, "WB", "R", {"Alpha": 2, "Plains": 17}, 4, 3),),
    win_rate_bucket=None,
    games_bucket=50,
)


def test_samples_round_trip_and_serialize_keys_in_order() -> None:
    text = samples_to_text([RECORD, RECORD])
    assert samples_from_text(text + "\n") == (RECORD, RECORD)
    assert text.index('"Alpha"') < text.index('"Dáin"')
    assert text.count("\n") == 2


def test_snapshots_round_trip_with_and_without_dates() -> None:
    snap = Snapshot(
        "SOS",
        SourceRef("games", dt.date(2026, 4, 21), dt.date(2026, 4, 26), "abc", 9),
        {"Alpha": CardCounts(1, 2, 3, 4, 5, 6)},
        {"WB": PairCounts(9, 5)},
    )
    assert snapshot_from_json(snapshot_to_json(snap)) == snap
    undated = Snapshot("SOS", SourceRef("games", None, None, None, 0), {}, {})
    assert snapshot_from_json(snapshot_to_json(undated)) == undated


def test_writes_are_utf8_lf_and_paths_are_per_set(tmp_path: Path) -> None:
    path = sample_path(tmp_path, "SOS")
    write_text(path, "Dáin\n")
    assert path.read_bytes() == "Dáin\n".encode()
    assert presplit_path(tmp_path, "SOS").name == "SOS.presplit.json"
    assert switch_path(tmp_path, "SOS") == tmp_path / "pools" / "SOS.switch.jsonl"
    assert not list(path.parent.glob("*.tmp"))


def test_read_json_of_a_missing_file_is_none(tmp_path: Path) -> None:
    assert read_json(tmp_path / "nope.json") is None
    write_text(tmp_path / "x.json", json_text({"b": 1, "a": [1]}))
    assert read_json(tmp_path / "x.json") == {"a": [1], "b": 1}


def test_reports_match_within_the_rounding_step_only() -> None:
    assert reports_match({"a": [0.5, "x", None]}, {"a": [0.50009, "x", None]})
    assert not reports_match({"a": 0.5}, {"a": 0.5003})
    assert not reports_match({"a": 0.5}, {"a": "0.5"})
    assert not reports_match({"a": 1}, {"b": 1})
    assert not reports_match([1, 2], [1])
    assert not reports_match("x", "y")


def test_booleans_match_only_booleans() -> None:
    assert reports_match({"a": True}, {"a": True})
    assert not reports_match({"a": True}, {"a": 1})
    assert not reports_match({"a": 1.0}, {"a": True})
    assert not reports_match({"a": False}, {"a": True})
