"""The private paste store (decision 0007). Made-up numbers; tmp_path data directories."""

from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
import random
from pathlib import Path

import pytest

from arena_wizard.datadir import PRIVATE_MARKER
from arena_wizard.domain.sets import EventType
from arena_wizard.domain.stats import CardCounts
from arena_wizard.pastes.parsers import PARSER_VERSION, CardDataRow, GradeRow
from arena_wizard.pastes.store import (
    PasteKey,
    StaleFile,
    StoredPaste,
    delete_paste,
    from_json,
    latest_card_data,
    latest_grades,
    read_pastes,
    source_label,
    to_json,
    to_snapshot,
    write_paste,
)

DAY = dt.date(2026, 10, 3)
AD, PD, SEALED = EventType.ARENA_DIRECT_SEALED, EventType.PREMIER_DRAFT, EventType.SEALED


def _card_paste(
    event: EventType = AD,
    day: dt.date = DAY,
    copied: dt.date | None = None,
    rows: tuple[CardDataRow, ...] = (CardDataRow("Made-up Knight", "W", "C", 120, 0.575, 40, 0.5),),
    source: str = "17lands-card-data",
) -> StoredPaste:
    return StoredPaste(
        key=PasteKey("FRA", "card-data", event, source, day),
        label="17Lands card data",
        url="https://example.invalid/never-fetched",
        copied_on=copied or day,
        published_on=None,
        columns=("Name", "# GIH", "GIH WR", "# GNS", "GNS WR"),
        text_sha256="ab" * 32,
        parser_version=PARSER_VERSION,
        card_rows=rows,
    )


def _grade_paste(source: str = "llu-marc", day: dt.date = DAY) -> StoredPaste:
    return StoredPaste(
        key=PasteKey("FRA", "grades", None, source, day),
        label="Marc Anderson, Limited Level-Ups",
        url=None,
        copied_on=day,
        published_on=dt.date(2026, 9, 25),
        columns=("Tier",),
        text_sha256="cd" * 32,
        parser_version=PARSER_VERSION,
        grade_rows=(GradeRow("Made-up Knight", "B+", 9.0), GradeRow("Made-up Relic", "TBD", None)),
    )


def test_the_key_is_the_path_under_the_data_directory(tmp_path: Path) -> None:
    assert _card_paste().key.path(tmp_path) == (
        tmp_path / "pastes/FRA/card-data/ArenaDirect_Sealed/17lands-card-data/2026-10-03.json"
    )
    assert _grade_paste().key.path(tmp_path) == (
        tmp_path / "pastes/FRA/grades/grades/llu-marc/2026-10-03.json"
    )


@pytest.mark.parametrize("paste", [_card_paste(), _grade_paste()])
def test_serialization_round_trips_and_is_deterministic(paste: StoredPaste) -> None:
    text = to_json(paste)
    assert from_json(text) == paste
    assert to_json(from_json(text)) == text
    assert text.endswith("}\n") and not text.endswith("\n\n")
    document = json.loads(text)
    assert list(document) == sorted(document)
    assert document["kind"] == PRIVATE_MARKER


def test_a_row_count_counts_whichever_dataset_the_paste_holds() -> None:
    assert _card_paste().row_count == 1 and _grade_paste().row_count == 2


def test_writing_twice_leaves_the_same_bytes_and_a_change_replaces_them(tmp_path: Path) -> None:
    paste = _card_paste()
    path = paste.key.path(tmp_path)
    assert write_paste(tmp_path, paste) is True
    first = hashlib.sha256(path.read_bytes()).hexdigest()
    assert write_paste(tmp_path, paste) is False
    assert hashlib.sha256(path.read_bytes()).hexdigest() == first
    changed = _card_paste(rows=(CardDataRow("Made-up Knight", "W", "C", 120, 0.6, 40, 0.5),))
    assert write_paste(tmp_path, changed) is True
    assert hashlib.sha256(path.read_bytes()).hexdigest() != first
    assert from_json(path.read_text(encoding="utf-8")).card_rows[0].gih_wr == 0.6
    assert [p.name for p in path.parent.iterdir()] == [path.name]


@pytest.mark.parametrize("field", ["format_version", "parser_version"])
def test_a_file_from_an_older_version_must_be_pasted_again(tmp_path: Path, field: str) -> None:
    write_paste(tmp_path, _grade_paste())
    stale = _card_paste()
    path = stale.key.path(tmp_path)
    document = json.loads(to_json(stale))
    document[field] = 0
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(StaleFile, match="paste it again"):
        from_json(path.read_text(encoding="utf-8"))
    pastes, problems = read_pastes(tmp_path, "FRA")
    assert pastes == (_grade_paste(),)
    assert problems == (
        "17Lands card data from 2026-10-03 was stored by an older version; paste it again",
    )


def test_reading_ignores_files_that_are_not_a_days_paste(tmp_path: Path) -> None:
    write_paste(tmp_path, _card_paste())
    folder = _card_paste().key.path(tmp_path).parent
    (folder / "notes.json").write_text("{}", encoding="utf-8")
    (folder / ".2026-10-04.json.123.tmp").write_text("partial", encoding="utf-8")
    assert read_pastes(tmp_path, "FRA") == ((_card_paste(),), ())
    assert read_pastes(tmp_path, "SOS") == ((), ())


def test_deleting_removes_one_paste_and_reports_a_missing_one(tmp_path: Path) -> None:
    write_paste(tmp_path, _card_paste())
    assert delete_paste(tmp_path, _card_paste().key) is True
    assert delete_paste(tmp_path, _card_paste().key) is False
    assert read_pastes(tmp_path, "FRA") == ((), ())


def test_the_newest_card_data_of_the_right_event_type_is_chosen_in_any_order() -> None:
    older = _card_paste(day=dt.date(2026, 10, 2))
    newest = _card_paste(day=dt.date(2026, 10, 4))
    same_day_earlier_copy = _card_paste(day=dt.date(2026, 10, 4), copied=dt.date(2026, 10, 1))
    draft = _card_paste(PD, day=dt.date(2026, 10, 9))
    pastes = [older, newest, same_day_earlier_copy, draft, _grade_paste()]
    for seed in range(5):
        random.Random(seed).shuffle(pastes)
        assert latest_card_data(pastes, AD, frozenset()) == newest
        assert latest_card_data(pastes, PD, frozenset()) == draft
    assert latest_card_data(pastes, SEALED, frozenset()) is None


def test_source_id_breaks_a_tie_on_both_days() -> None:
    a = _card_paste(source="a-source")
    b = _card_paste(source="b-source")
    assert latest_card_data([b, a], AD, frozenset()) == b
    assert latest_card_data([a, b], AD, frozenset()) == b


def test_card_data_covered_by_a_public_file_is_never_chosen() -> None:
    assert latest_card_data([_card_paste(PD)], PD, frozenset({PD})) is None


def test_the_newest_grades_of_each_source_are_chosen_in_source_order() -> None:
    old = _grade_paste("llu-marc", dt.date(2026, 9, 30))
    new = _grade_paste("llu-marc", dt.date(2026, 10, 2))
    lsv = _grade_paste("tcgplayer-lsv", dt.date(2026, 9, 29))
    assert latest_grades([lsv, new, _card_paste(), old]) == (new, lsv)
    assert latest_grades([_card_paste()]) == ()


def test_a_snapshot_keeps_only_counts_with_rates_and_rounds_wins() -> None:
    rows = (
        CardDataRow("Full", "W", "C", 200, 0.5525, 80, 0.4937),
        CardDataRow("No Not Seen Rate", "W", "C", 100, 0.6, 30, None),
        CardDataRow("No Not Seen Games", "W", "C", 100, 0.6, 0, 0.5),
        CardDataRow("Blank Rate", "W", "C", 40, None, 10, 0.5),
        CardDataRow("No Games", "W", "C", 0, 0.5, None, None),
        CardDataRow("Missing", "W", "C", None, None, None, None),
    )
    snapshot = to_snapshot(_card_paste(rows=rows))
    assert snapshot.cards == {
        "Full": CardCounts(games_gih=200, wins_gih=110, games_gns=80, wins_gns=39),
        "No Not Seen Rate": CardCounts(games_gih=100, wins_gih=60),
        "No Not Seen Games": CardCounts(games_gih=100, wins_gih=60),
    }
    assert snapshot.set_code == "FRA" and snapshot.pairs == {}
    assert snapshot.source.label == "17Lands card data" and snapshot.source.first_day is None


def test_labels_use_readable_event_names_and_the_copy_day() -> None:
    assert source_label(_card_paste(copied=dt.date(2026, 10, 1))) == (
        "17Lands card data, Arena Direct Sealed, pasted by hand, copied 2026-10-01"
    )
    assert source_label(_card_paste(PD)).startswith("17Lands card data, Premier Draft,")
    assert source_label(_grade_paste()) == (
        "Marc Anderson, Limited Level-Ups, pasted by hand, copied 2026-10-03"
    )


def test_a_paste_with_a_publication_date_keeps_it() -> None:
    paste = dataclasses.replace(_card_paste(), published_on=dt.date(2026, 9, 20))
    assert from_json(to_json(paste)).published_on == dt.date(2026, 9, 20)
