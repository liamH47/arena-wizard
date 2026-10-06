"""The `paste` and `pastes` commands (decisions 0005 and 0007), on made-up numbers."""

from __future__ import annotations

import dataclasses
import datetime as dt
import random
from pathlib import Path

import pytest

from arena_wizard import paste_commands
from arena_wizard.catalog import load_packaged_card_table
from arena_wizard.cli import decode_text
from arena_wizard.domain.sets import EventType, load_set_config
from arena_wizard.etl.game_cache import counts_path
from arena_wizard.paste_commands import PasteRequest, covered_event_types, text_sha256
from arena_wizard.pastes.parsers import GradeRow
from arena_wizard.pastes.store import PasteKey, StoredPaste, read_pastes, write_paste

FRA = load_set_config("FRA")
DAY = dt.date(2026, 10, 3)
LETTERS = ("A+", "A", "A-", "B+", "B", "B-", "C+", "C", "C-", "D+", "D", "F", "SB")
CARD_HEADER = [
    "Name", "Color", "Rarity", "# Seen", "ALSA", "# Picked", "ATA", "# GP", "% GP", "GP WR",
    "# OH", "OH WR", "# GD", "GD WR", "# GIH", "GIH WR", "# GNS", "GNS WR", "IIH",
]  # fmt: skip


def set_names(code: str) -> list[str]:
    """Every non-basic front-face name in a set's card table, sorted."""
    return sorted({c.front_name for c in load_packaged_card_table(code).cards if not c.is_basic})


def _quote(cells: list[str]) -> str:
    return ",".join(f'"{cell}"' for cell in cells)


def grades_csv(
    code: str = "FRA", seed: int = 1, extra: tuple[str, ...] = (), tbd: int = 0
) -> bytes:
    """A made-up Limited Level-Ups style tier list for every card in a set; the first `tbd`
    cards are left ungraded."""
    rng = random.Random(seed)
    names = [*set_names(code), *extra]
    grades = ["TBD" if i < tbd else rng.choice(LETTERS) for i in range(len(names))]
    rows = [_quote([n, g, "", "", ""]) for n, g in zip(names, grades, strict=True)]
    header = _quote(["Name", "Tier", "Buildaround", "Synergy", "Comment"])
    return ("﻿" + "\n".join([header, *rows])).encode("utf-8")


def card_data_csv(
    code: str = "FRA",
    seed: int = 1,
    *,
    draft: bool = False,
    not_seen: bool = True,
    extra: tuple[str, ...] = (),
) -> bytes:
    """A made-up 17Lands card-data export in the Download as CSV layout."""
    rng = random.Random(seed)
    header = CARD_HEADER if not_seen else [c for c in CARD_HEADER if c not in ("# GNS", "GNS WR")]
    rows = []
    for name in [*set_names(code), *extra]:
        games, rate = rng.randint(200, 9000), rng.uniform(0.48, 0.62)
        unseen, unseen_rate = rng.randint(100, 4000), rng.uniform(0.45, 0.56)
        # A Sealed export counts seen and picked cards but leaves pick positions blank.
        picks = [str(games * 3), "4.50", str(games), "5.10"] if draft else ["0", "", "0", ""]
        cells = dict(
            zip(
                CARD_HEADER,
                [name, "W", "C", *picks, "", "", "", "", "", "", "",
                 str(games), f"{rate * 100:.1f}%", str(unseen), f"{unseen_rate * 100:.1f}%",
                 f"{(rate - unseen_rate) * 100:.1f}pp"],
                strict=True,
            )
        )  # fmt: skip
        rows.append(_quote([cells[c] for c in header]))
    return ("﻿" + "\n".join([_quote(header), *rows])).encode("utf-8")


def request(
    dataset: str = "grades",
    source: str = "llu-marc",
    event: EventType | None = None,
    **changes: object,
) -> PasteRequest:
    base = PasteRequest("FRA", dataset, source, event, None, None, None, False)
    return dataclasses.replace(base, **changes)  # type: ignore[arg-type]


def ad_request(**changes: object) -> PasteRequest:
    return request("card-data", "17lands-card-data", EventType.ARENA_DIRECT_SEALED, **changes)


def run_paste(
    req: PasteRequest,
    data: bytes,
    data_dir: Path,
    today: dt.date = DAY,
    cache: Path | None = None,
) -> tuple[int, list[str]]:
    lines: list[str] = []
    status = paste_commands.paste(
        req,
        data,
        load_set_config(req.set_code),
        data_dir,
        cache or data_dir.parent / "cache",
        today,
        decode_text,
        lines.append,
    )
    return status, lines


def tree(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


# --- storing, idempotency ------------------------------------------------------------------


def test_pasting_twice_stores_one_identical_file_and_says_nothing_changed(tmp_path: Path) -> None:
    data = tmp_path / "data"
    status, lines = run_paste(request(), grades_csv(), data)
    assert status == 0
    assert lines[0].startswith("Stored: Marc Anderson, Limited Level-Ups, pasted by hand, copied ")
    assert "289 rows" in lines[0] and "never committed" in lines[0]
    assert lines[1].startswith("Copied-on defaulted to today, 2026-10-03 UTC")
    first = tree(data)
    assert len(first) == 1
    assert run_paste(request(), grades_csv(), data) == (
        0,
        ["Identical to today's stored paste from this source; nothing changed."],
    )
    assert tree(data) == first


def test_a_changed_cell_the_same_day_replaces_the_file_in_place(tmp_path: Path) -> None:
    data = tmp_path / "data"
    run_paste(ad_request(), card_data_csv(seed=1), data)
    before = tree(data)
    status, lines = run_paste(ad_request(), card_data_csv(seed=2), data)
    after = tree(data)
    assert status == 0 and lines[0].startswith("Replaced today's paste: ")
    assert "(was 289)" in lines[0]
    assert after.keys() == before.keys() and after != before


def test_the_next_utc_day_adds_a_second_file(tmp_path: Path) -> None:
    data = tmp_path / "data"
    run_paste(request(), grades_csv(), data)
    run_paste(request(), grades_csv(), data, today=DAY + dt.timedelta(days=1))
    assert len(tree(data)) == 2


def test_an_explicit_copy_date_is_stored_and_not_reported_as_defaulted(tmp_path: Path) -> None:
    status, lines = run_paste(
        request(copied_on=DAY - dt.timedelta(days=2), published_on=dt.date(2026, 9, 25)),
        grades_csv(),
        tmp_path / "data",
    )
    assert status == 0 and len(lines) == 1 and "copied 2026-10-01" in lines[0]
    (paste,), _ = read_pastes(tmp_path / "data", "FRA")
    assert paste.published_on == dt.date(2026, 9, 25)


def test_unknown_names_are_skipped_and_listed(tmp_path: Path) -> None:
    extra = tuple(f"Made-up Card {i}" for i in range(7))
    status, lines = run_paste(ad_request(), card_data_csv(extra=extra), tmp_path / "data")
    assert status == 0
    assert lines[-1].startswith("7 names are not FRA cards and were skipped: 'Made-up Card 0'")
    assert lines[-1].endswith(", and 2 more.")
    status, lines = run_paste(request(), grades_csv(extra=extra[:2]), tmp_path / "other")
    assert lines[-1] == (
        "2 names are not FRA cards and were skipped: 'Made-up Card 0', 'Made-up Card 1'."
    )


def test_a_paste_without_not_seen_columns_is_stored_with_a_warning(tmp_path: Path) -> None:
    status, lines = run_paste(ad_request(), card_data_csv(not_seen=False), tmp_path / "data")
    assert status == 0
    assert lines[-1].startswith('No "Not Seen" columns in this paste')


def test_a_premier_draft_paste_keeps_its_pick_columns(tmp_path: Path) -> None:
    req = request("card-data", "17lands-card-data", EventType.PREMIER_DRAFT)
    status, lines = run_paste(req, card_data_csv(draft=True), tmp_path / "data")
    assert status == 0 and "Premier Draft, pasted by hand" in lines[0]


# --- refusals write nothing -------------------------------------------------------------------


REFUSALS = [
    (request(source="draftsim"), grades_csv(), "draftsim is not accepted"),
    (request(source="nobody"), grades_csv(), "unknown source 'nobody'"),
    (request(dataset="card-data"), grades_csv(), "llu-marc provides grades, not card-data"),
    (
        request("card-data", "17lands-card-data"),
        card_data_csv(),
        "card data needs --event-type",
    ),
    (request(event=EventType.SEALED), grades_csv(), "grades take no --event-type"),
    (request(copied_on=DAY + dt.timedelta(days=1)), grades_csv(), "is after today"),
    (request(published_on=DAY + dt.timedelta(days=1)), grades_csv(), "is after today"),
    (ad_request(copied_on=dt.date(2026, 9, 28)), card_data_csv(), "before FRA reached Arena"),
    (request(), b"x" * 5_000_001, "is over 5,000,000 bytes"),
    (request(), b"Name,Stars\nA,3", "grade column"),
    (ad_request(), card_data_csv(draft=True), "average pick positions"),
    (request(), grades_csv("SOS"), "not FRA cards"),
]


@pytest.mark.parametrize(("req", "data", "message"), REFUSALS, ids=[r[2] for r in REFUSALS])
def test_a_refused_paste_writes_nothing_and_says_why(
    tmp_path: Path, req: PasteRequest, data: bytes, message: str
) -> None:
    data_dir = tmp_path / "data"
    run_paste(request(), grades_csv(seed=9), data_dir)
    before = tree(data_dir)
    status, lines = run_paste(req, data, data_dir)
    assert status == 1
    assert lines == [lines[0]] and lines[0].startswith("Refused, nothing stored: ")
    assert message in lines[0]
    assert tree(data_dir) == before


def test_a_cached_public_file_refuses_the_paste_only_after_the_embargo(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    path = counts_path(cache, "FRA", EventType.PREMIER_DRAFT)
    path.parent.mkdir(parents=True)
    path.write_text("{}", encoding="utf-8")
    req = request("card-data", "17lands-card-data", EventType.PREMIER_DRAFT)
    before_embargo = dt.date(2026, 10, 9)
    assert run_paste(req, card_data_csv(draft=True), tmp_path / "a", before_embargo, cache)[0] == 0
    status, lines = run_paste(
        req, card_data_csv(draft=True), tmp_path / "b", FRA.embargo_until, cache
    )
    assert status == 1 and "already cached" in lines[0] and "rule 4" in lines[0]
    assert not (tmp_path / "b").exists()
    assert covered_event_types(FRA, cache, FRA.embargo_until) == {EventType.PREMIER_DRAFT}
    assert covered_event_types(FRA, cache, before_embargo) == frozenset()


def test_the_same_text_under_another_source_is_refused(tmp_path: Path) -> None:
    data = tmp_path / "data"
    run_paste(request(), grades_csv(), data)
    before = tree(data)
    status, lines = run_paste(request(source="llu-alex"), grades_csv(), data)
    assert status == 1
    assert "same text as the Marc Anderson, Limited Level-Ups paste from 2026-10-03" in lines[0]
    assert tree(data) == before


def _big_old_paste(data_dir: Path) -> None:
    rows = tuple(GradeRow(f"Card {i:04}", "B", 8.0) for i in range(700))
    key = PasteKey("FRA", "grades", None, "llu-marc", DAY)
    write_paste(
        data_dir,
        StoredPaste(key, "Marc Anderson, Limited Level-Ups", None, DAY, None, ("Tier",),
                    "0" * 64, 1, (), rows),
    )  # fmt: skip


def test_a_much_smaller_paste_needs_replace(tmp_path: Path) -> None:
    data = tmp_path / "data"
    _big_old_paste(data)
    before = tree(data)
    status, lines = run_paste(request(), grades_csv(), data)
    assert status == 1 and "has 700 rows and this one has 289" in lines[0]
    assert tree(data) == before
    status, lines = run_paste(request(replace=True), grades_csv(), data)
    assert status == 0 and "(was 700)" in lines[0]


def test_the_text_hash_ignores_a_byte_order_mark_and_carriage_returns() -> None:
    assert text_sha256("﻿a\r\nb") == text_sha256("a\nb")


# --- listing and deleting --------------------------------------------------------------------


def _listed(data_dir: Path) -> list[str]:
    lines: list[str] = []
    assert paste_commands.list_pastes("FRA", data_dir, lines.append) == 0
    return lines


def test_listing_with_nothing_stored_says_none(tmp_path: Path) -> None:
    assert _listed(tmp_path) == [f"FRA pastes, private, in {tmp_path}:", "  none"]


def test_listing_shows_each_paste_and_every_stale_file(tmp_path: Path) -> None:
    run_paste(request(), grades_csv(), tmp_path)
    run_paste(ad_request(), card_data_csv(), tmp_path)
    stale = PasteKey("FRA", "grades", None, "llu-alex", DAY).path(tmp_path)
    stale.parent.mkdir(parents=True)
    stale.write_text(
        '{"format_version": 1, "parser_version": 0, "label": "Old", "import_day": "2026-10-01"}',
        encoding="utf-8",
    )
    lines = _listed(tmp_path)
    assert lines[1] == (
        "  card-data/ArenaDirect_Sealed/17lands-card-data/2026-10-03  17Lands card data, "
        "copied 2026-10-03, 289 rows"
    )
    assert lines[2].startswith("  grades/grades/llu-marc/2026-10-03  Marc Anderson")
    assert lines[3] == "  Old from 2026-10-01 was stored by an older version; paste it again"


def _delete(data_dir: Path, key: str) -> tuple[int, list[str]]:
    lines: list[str] = []
    return paste_commands.delete("FRA", key, data_dir, lines.append), lines


def test_deleting_a_paste_by_its_listed_key(tmp_path: Path) -> None:
    run_paste(ad_request(), card_data_csv(), tmp_path)
    run_paste(request(), grades_csv(), tmp_path)
    key = "card-data/ArenaDirect_Sealed/17lands-card-data/2026-10-03"
    assert _delete(tmp_path, key) == (0, [f"Deleted {key}."])
    assert _delete(tmp_path, "/grades/grades/llu-marc/2026-10-03/")[0] == 0
    assert tree(tmp_path) == {}
    assert _delete(tmp_path, key) == (1, [f"No stored paste {key}."])


@pytest.mark.parametrize(
    "key",
    [
        "grades/llu-marc/2026-10-03",
        "card-data/Nope/17lands-card-data/2026-10-03",
        "grades/grades/draftsim/2026-10-03",
        "grades/grades/llu-marc/yesterday",
    ],
)
def test_a_malformed_key_is_refused(tmp_path: Path, key: str) -> None:
    status, lines = _delete(tmp_path, key)
    assert status == 1 and lines[0].startswith(f"Not a paste key: {key!r}.")
