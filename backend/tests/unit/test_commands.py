from __future__ import annotations

import copy
import datetime as dt
import gzip
import hashlib
import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from arena_wizard import commands
from arena_wizard.catalog import load_packaged_card_table
from arena_wizard.domain.cards import Card
from arena_wizard.domain.sets import EventType, Format
from arena_wizard.domain.stats import Snapshot
from arena_wizard.etl import game_cache, games
from arena_wizard.etl.game_cache import file_path
from arena_wizard.eval.report import render_markdown
from arena_wizard.eval.storage import (
    EVAL_DIR,
    presplit_path,
    read_json,
    sample_path,
    samples_from_text,
    snapshot_from_json,
    switch_path,
)
from arena_wizard.sources.seventeenlands_files import public_file_url
from tests.conftest import ChunkedBody, FakeClock, make_context
from tests.seventeenlands_fixture import file_bytes, header, row

TODAY = dt.date(2026, 9, 29)
SOS_BEFORE_EMBARGO = dt.date(2026, 4, 25)


# --- load-file ---------------------------------------------------------------------------


def _bucket(body: bytes) -> Callable[[httpx.Request], httpx.Response]:
    def handle(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == public_file_url("SOS", EventType.SEALED)
        if request.method == "HEAD":
            return httpx.Response(200, headers={"ETag": '"v1"'})
        return httpx.Response(200, headers={"ETag": '"v1"'}, stream=ChunkedBody(body))

    return handle


def _load(body: bytes, cache: Path) -> list[str]:
    lines: list[str] = []
    ctx = make_context(_bucket(body), FakeClock())
    assert commands.load_game_file("SOS", EventType.SEALED, ctx, cache, lines.append) == 0
    return lines


def test_loading_a_file_says_downloaded_then_unchanged_then_recounted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = _load(file_bytes(), tmp_path)
    assert first[0].startswith("SOS Sealed: downloaded; 2 days (2026-04-21 to 2026-04-22)")
    assert hashlib.sha256(file_bytes()).hexdigest()[:16] in first[0]
    assert _load(file_bytes(), tmp_path)[0].startswith("SOS Sealed: unchanged, cache kept;")
    monkeypatch.setattr(game_cache, "COUNTS_VERSION", games.COUNTS_VERSION + 1)
    recounted = _load(file_bytes(), tmp_path)[0]
    assert recounted.startswith("SOS Sealed: recounted from the cached file;")


def test_a_file_with_no_games_reports_no_days(tmp_path: Path) -> None:
    empty = gzip.compress((header() + "\n").encode("utf-8"), mtime=0)
    assert "0 days (- to -)" in _load(empty, tmp_path)[0]


def test_statistics_are_none_until_a_file_is_loaded_then_cover_every_game(
    tmp_path: Path,
) -> None:
    assert commands.statistics_for("SOS", tmp_path) is None
    _load(file_bytes(), tmp_path)
    stats = commands.statistics_for("SOS", tmp_path)
    assert stats is not None
    assert stats.source.label == commands.SEALED_LABEL
    assert stats.source.games == 4
    assert stats.source.content_sha256 == hashlib.sha256(file_bytes()).hexdigest()


# --- build -------------------------------------------------------------------------------


def _first_printing(code: str) -> dict[str, Card]:
    printings: dict[str, Card] = {}
    for card in load_packaged_card_table(code).cards:
        printings.setdefault(card.front_name, card)
    return printings


def _sample_pool() -> dict[str, int]:
    """A real SOS pool from the committed evaluation sample (public 17Lands data)."""
    line = sample_path(EVAL_DIR, "SOS").read_text(encoding="utf-8").splitlines()[0]
    pool: dict[str, int] = json.loads(line)["pool"]
    return pool


def _export(pool: dict[str, int]) -> list[str]:
    printings = _first_printing("SOS")
    return [
        f"{count} {printings[name].name} ({printings[name].set_code}) "
        f"{printings[name].collector_number}"
        for name, count in pool.items()
    ]


def _stats() -> Snapshot:
    return snapshot_from_json(presplit_path(EVAL_DIR, "SOS").read_text(encoding="utf-8"))


def _build(text: str, stats: Snapshot | None, today: dt.date = TODAY) -> tuple[int, list[str]]:
    lines: list[str] = []
    status = commands.build("SOS", Format.BO1_SEALED, text, stats, today, lines.append)
    return status, lines


def test_a_real_pool_with_statistics_prints_ranked_decks_with_breakdowns_and_lists() -> None:
    status, lines = _build("\n".join(_export(_sample_pool())), _stats())
    assert status == 0
    assert lines[0] == "SOS pool: 83 non-basic cards (SOS pools run 81 to 85)."
    assert lines[1].startswith("Statistics: 17Lands public Sealed game data (pre-split), ")
    assert lines[1].endswith("(28,374 games).")
    ranks = [line for line in lines if line.startswith("#")]
    assert ranks[0].startswith("#1 ") and ranks[1].startswith("#2 ")
    assert lines.count("  Breakdown (score points):") == len(ranks)
    assert lines.count("  Deck (click these into Arena):") == len(ranks)
    assert any(line.startswith("    card quality") for line in lines)
    assert "" in lines


def test_without_statistics_the_build_refuses_and_names_the_load_command() -> None:
    status, lines = _build("\n".join(_export(_sample_pool())), None)
    assert status == 1
    assert lines[-1].endswith("Load them with: arena-wizard load-file --set SOS")
    assert not any(line.startswith("#") for line in lines)


def test_statistics_before_the_embargo_date_are_switched_off() -> None:
    status, lines = _build("\n".join(_export(_sample_pool())), _stats(), SOS_BEFORE_EMBARGO)
    assert status == 1
    assert lines[0].startswith("SOS reached Arena on 2026-04-21.")
    assert "until 2026-05-02" in lines[0]
    assert "https://www.17lands.com/usage_guidelines" in lines[0]
    assert lines[-1].startswith("No statistics for SOS")


def test_statistics_on_the_embargo_date_are_used() -> None:
    status, lines = _build("\n".join(_export(_sample_pool())), _stats(), dt.date(2026, 5, 2))
    assert status == 0
    assert not any("reached Arena" in line for line in lines)


def test_a_pool_too_small_for_any_deck_says_so() -> None:
    small = dict(list(_sample_pool().items())[:5])
    status, lines = _build("\n".join(_export(small)), _stats())
    assert status == 1
    assert lines[-1] == "No color pair has enough castable spells for a 40-card deck."


def test_warnings_are_grouped_by_what_the_player_should_do() -> None:
    sos = _first_printing("SOS")
    name = next(n for n in sorted(sos) if len(n) > 10 and sos[n].set_code == "SOS")
    hob = next(c for c in _first_printing("HOB").values() if "Basic" not in c.type_line)
    lines = [
        *_export(_sample_pool()),
        f"1 {name[:-2]}xx (SOS) 9998",
        "this is not an export line",
        f"1 {hob.name} ({hob.set_code}) {hob.collector_number}",
        f"1 {name} (SOS) 9999",
    ]
    status, out = _build("\n".join(lines), None)
    assert status == 1
    unknown = out.index("Not recognised, in no deck (1):")
    assert out[unknown + 1].startswith(f"  line {len(lines) - 3}: ")
    assert f"Did you mean: {name}" in out[unknown + 1]
    unparsed = out.index("Not an export line, ignored (1):")
    assert out[unparsed + 1] == f"  line {len(lines) - 2}: this is not an export line"
    assert any(line.startswith("From another set: ") and hob.front_name in line for line in out)
    assert "1 lines matched by card name rather than set and number; values are unaffected." in (
        out
    )


def test_an_unknown_name_without_close_matches_gets_no_suggestion() -> None:
    status, out = _build("1 Zzzzqqqq Xxxxwwww (SOS) 9998", None)
    assert status == 1
    assert "  line 1: 1 Zzzzqqqq Xxxxwwww (SOS) 9998." in out


# --- eval build-set ----------------------------------------------------------------------

# Games per day 4, 1, 3: 60% of 8 games is reached on day 22, so pools first seen on day 23
# are eligible. d3 registered two two-color builds, so it is also a switch pool.
EVAL_ROWS = [
    *(row("d1", 0, "2026-04-21", "WB", i % 2 == 0, (1, 1, 17)) for i in range(4)),
    row("d2", 0, "2026-04-22", "UR", True, (1, 0, 17), sideboard=(0, 1, 0)),
    row("d3", 0, "2026-04-23", "WB", True, (1, 1, 17), hand=(1, 0, 0)),
    row("d3", 1, "2026-04-23", "UR", False, (0, 1, 17), sideboard=(1, 0, 0)),
    row("d4", 0, "2026-04-23", "WB", False, (1, 1, 17), drawn=(0, 1, 0)),
]


def _eval_bytes(rows: list[str] = EVAL_ROWS) -> bytes:
    return gzip.compress(("\n".join([header(), *rows]) + "\n").encode("utf-8"), mtime=0)


def test_deriving_an_eval_set_splits_at_sixty_percent_and_pins_what_it_derived() -> None:
    data = _eval_bytes()
    derived = commands.derive_eval_set("SOS", data, 600)
    pin = derived.pin
    assert pin["url"] == public_file_url("SOS", EventType.SEALED)
    assert pin["sha256"] == hashlib.sha256(data).hexdigest()
    assert (pin["bytes"], pin["games"], pin["pools"]) == (len(data), 8, 4)
    assert pin["split_day"] == "2026-04-22"
    assert pin["eligible_pool_share"] == pytest.approx(2 / 4)
    assert pin["eligible_game_share"] == pytest.approx(3 / 8)
    sample = samples_from_text(derived.sample_text)
    assert sorted(r.draft_id for r in sample) == ["d3", "d4"]
    assert pin["sample_size"] == 2
    assert [r.draft_id for r in samples_from_text(derived.switch_text)] == ["d3"]
    assert pin["switch_size"] == 1
    presplit = snapshot_from_json(derived.presplit_text)
    assert presplit.source.games == 5
    assert presplit.source.last_day == dt.date(2026, 4, 22)
    for key, text in (
        ("sample_sha256", derived.sample_text),
        ("switch_sha256", derived.switch_text),
        ("presplit_sha256", derived.presplit_text),
    ):
        assert pin[key] == hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert commands.derive_eval_set("SOS", data, 600) == derived


def test_the_sample_size_caps_the_sample() -> None:
    assert commands.derive_eval_set("SOS", _eval_bytes(), 1).pin["sample_size"] == 1


def _cache_file(cache: Path, code: str, data: bytes) -> None:
    path = file_path(cache, code, EventType.SEALED)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _tree(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_building_the_eval_set_writes_files_and_pins_and_is_idempotent(tmp_path: Path) -> None:
    cache, eval_dir = tmp_path / "cache", tmp_path / "eval"
    _cache_file(cache, "SOS", _eval_bytes())
    lines: list[str] = []
    assert commands.build_eval_set(("SOS",), 600, False, eval_dir, cache, lines.append) == 0
    assert lines == ["SOS: 2 sample pools and 1 switch pools of 4; split day 2026-04-22"]
    pins = read_json(eval_dir / "pins.json")
    assert pins["SOS"] == commands.derive_eval_set("SOS", _eval_bytes(), 600).pin
    for path in (
        sample_path(eval_dir, "SOS"),
        switch_path(eval_dir, "SOS"),
        presplit_path(eval_dir, "SOS"),
    ):
        assert path.is_file()
    first = _tree(eval_dir)
    assert commands.build_eval_set(("SOS",), 600, False, eval_dir, cache, lines.append) == 0
    assert _tree(eval_dir) == first


def test_a_reuploaded_file_is_refused_until_repinned(tmp_path: Path) -> None:
    cache, eval_dir = tmp_path / "cache", tmp_path / "eval"
    _cache_file(cache, "SOS", _eval_bytes())
    commands.build_eval_set(("SOS",), 600, False, eval_dir, cache, lambda _: None)
    before = _tree(eval_dir)
    changed = _eval_bytes([*EVAL_ROWS, row("d5", 0, "2026-04-23", "WB", True, (1, 1, 17))])
    _cache_file(cache, "SOS", changed)
    lines: list[str] = []
    assert commands.build_eval_set(("SOS",), 600, False, eval_dir, cache, lines.append) == 1
    assert "17Lands re-uploaded it. Re-run with --repin to accept it." in lines[0]
    assert hashlib.sha256(changed).hexdigest()[:16] in lines[0]
    assert _tree(eval_dir) == before
    assert commands.build_eval_set(("SOS",), 600, True, eval_dir, cache, lines.append) == 0
    assert read_json(eval_dir / "pins.json")["SOS"]["sha256"] == hashlib.sha256(changed).hexdigest()


def test_a_missing_cached_file_writes_nothing_for_any_set(tmp_path: Path) -> None:
    cache, eval_dir = tmp_path / "cache", tmp_path / "eval"
    _cache_file(cache, "SOS", _eval_bytes())
    lines: list[str] = []
    assert commands.build_eval_set(("SOS", "HOB"), 600, False, eval_dir, cache, lines.append) == 1
    assert lines == ["HOB: no cached Sealed file; run arena-wizard load-file --set HOB"]
    assert not eval_dir.exists()


def test_without_a_cache_argument_the_default_cache_is_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ARENA_WIZARD_CACHE_DIR", str(tmp_path / "cache"))
    _cache_file(tmp_path / "cache", "SOS", _eval_bytes())
    eval_dir = tmp_path / "eval"
    assert commands.build_eval_set(("SOS",), 600, False, eval_dir, None, lambda _: None) == 0
    assert (eval_dir / "pins.json").is_file()


# --- verdict -----------------------------------------------------------------------------


def _committed() -> tuple[dict[str, Any], str]:
    report: dict[str, Any] = read_json(EVAL_DIR / "report.json")
    return report, (EVAL_DIR / "report.md").read_text(encoding="utf-8")


def test_the_committed_report_passes_its_own_check() -> None:
    report, md = _committed()
    assert commands.verdict(report, report, md, True, report, []) == ()


def test_a_changed_metric_makes_the_committed_report_stale_in_check_mode_only() -> None:
    report, md = _committed()
    fresh = copy.deepcopy(report)
    fresh["sets"]["SOS"]["metrics"]["legality"] = 0.5
    problems = commands.verdict(fresh, report, md, True, None, [])
    assert problems[0] == "report.json is stale: re-run arena-wizard eval run and commit it"
    assert any(p.startswith("gate: SOS legality: ") for p in problems)
    assert not any("stale" in p for p in commands.verdict(fresh, report, md, False, None, []))


def test_a_missing_committed_report_is_stale() -> None:
    report, md = _committed()
    assert commands.verdict(report, None, md, True, None, [])[0].startswith("report.json is stale")


def test_a_hand_edited_markdown_report_is_caught() -> None:
    report, md = _committed()
    assert render_markdown(report) == md
    problems = commands.verdict(report, report, md + "edited\n", True, None, [])
    assert problems == ("report.md does not match report.json: re-run arena-wizard eval run",)
    assert commands.verdict(report, report, None, True, None, []) == problems


# --- eval run ----------------------------------------------------------------------------


def _small_eval_dir(root: Path, pools: int = 12, switch: int = 3) -> Path:
    """A trimmed copy of the committed SOS evaluation files, pinned to what was copied."""
    eval_dir = root / "backend" / "eval"
    texts = {
        sample_path(eval_dir, "SOS"): sample_path(EVAL_DIR, "SOS").read_bytes().splitlines(True),
        switch_path(eval_dir, "SOS"): switch_path(EVAL_DIR, "SOS").read_bytes().splitlines(True),
    }
    sample = b"".join(texts[sample_path(eval_dir, "SOS")][:pools])
    switches = b"".join(texts[switch_path(eval_dir, "SOS")][:switch])
    presplit = presplit_path(EVAL_DIR, "SOS").read_bytes()
    files = {
        sample_path(eval_dir, "SOS"): sample,
        switch_path(eval_dir, "SOS"): switches,
        presplit_path(eval_dir, "SOS"): presplit,
    }
    for path, data in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    pin = read_json(EVAL_DIR / "pins.json")["SOS"] | {
        "sample_sha256": hashlib.sha256(sample).hexdigest(),
        "switch_sha256": hashlib.sha256(switches).hexdigest(),
        "presplit_sha256": hashlib.sha256(presplit).hexdigest(),
        "sample_size": pools,
        "switch_size": switch,
    }
    (eval_dir / "pins.json").write_text(json.dumps({"SOS": pin}), encoding="utf-8")
    return eval_dir


def test_running_the_eval_without_pins_says_to_build_the_set_first(tmp_path: Path) -> None:
    lines: list[str] = []
    assert commands.run_eval(tmp_path, False, None, lines.append) == 1
    assert lines == ["No pinned evaluation sets; run arena-wizard eval build-set first."]


def test_a_tampered_or_missing_eval_file_stops_the_run(tmp_path: Path) -> None:
    eval_dir = _small_eval_dir(tmp_path)
    switch = switch_path(eval_dir, "SOS")
    switch.write_bytes(switch.read_bytes() + b"\n")
    lines: list[str] = []
    assert commands.run_eval(eval_dir, False, None, lines.append) == 1
    assert lines == ["SOS: SOS.switch.jsonl is missing or does not match its pin"]
    sample_path(eval_dir, "SOS").unlink()
    lines.clear()
    assert commands.run_eval(eval_dir, False, None, lines.append) == 1
    assert lines == ["SOS: SOS.sample.jsonl is missing or does not match its pin"]
    assert not (eval_dir / "report.json").exists()


@pytest.fixture(scope="module")
def evaluated(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A trimmed eval directory after one writing run, shared read-only by the tests below."""
    root = tmp_path_factory.mktemp("evaluated")
    eval_dir = _small_eval_dir(root)
    lines: list[str] = []
    commands.run_eval(eval_dir, False, None, lines.append)
    (root / "first-run.txt").write_text("\n".join(lines), encoding="utf-8")
    return root


def _copy(evaluated: Path, tmp_path: Path) -> tuple[Path, list[str]]:
    shutil.copytree(evaluated, tmp_path, dirs_exist_ok=True)
    first = (tmp_path / "first-run.txt").read_text(encoding="utf-8").splitlines()
    return tmp_path / "backend" / "eval", first


def test_running_the_eval_writes_the_report_and_check_mode_confirms_it(
    evaluated: Path, tmp_path: Path
) -> None:
    eval_dir, first = _copy(evaluated, tmp_path)
    assert first[0] == "SOS: evaluated 12 pools and 3 switch pools"
    report = read_json(eval_dir / "report.json")
    assert (eval_dir / "report.md").read_text(encoding="utf-8") == render_markdown(report)
    provenance = report["sets"]["SOS"]["provenance"]
    assert provenance["card_table_sha256"] is not None
    assert "curated_bombs_sha256" in provenance
    written = _tree(eval_dir)
    lines: list[str] = []
    commands.run_eval(eval_dir, True, None, lines.append)
    assert lines == first
    assert _tree(eval_dir) == written


def test_check_mode_reports_a_stale_report_without_rewriting_it(
    evaluated: Path, tmp_path: Path
) -> None:
    eval_dir, _ = _copy(evaluated, tmp_path)
    report = read_json(eval_dir / "report.json")
    report["sets"]["SOS"]["metrics"]["legality"] = 0.5
    (eval_dir / "report.json").write_text(json.dumps(report), encoding="utf-8")
    before = _tree(eval_dir)
    lines: list[str] = []
    assert commands.run_eval(eval_dir, True, None, lines.append) == 1
    assert "report.json is stale: re-run arena-wizard eval run and commit it" in lines
    assert _tree(eval_dir) == before


def test_an_accepted_exception_counts_only_while_its_decision_file_exists(
    evaluated: Path, tmp_path: Path
) -> None:
    eval_dir, first = _copy(evaluated, tmp_path)
    failures = [line for line in first if line.startswith("gate: SOS ")]
    assert failures, "the trimmed sample is expected to fail at least one absolute check"
    base = read_json(eval_dir / "report.json")
    decision = "docs/decisions/0099-accepted.md"
    checks = [line.removeprefix("gate: SOS ").split(":")[0] for line in failures]

    def gate_lines(entries: list[dict[str, str]]) -> tuple[int, list[str]]:
        (eval_dir / "accepted.json").write_text(json.dumps(entries), encoding="utf-8")
        lines: list[str] = []
        status = commands.run_eval(eval_dir, True, base, lines.append)
        return status, [line for line in lines if line.startswith("gate: ")]

    digest = {"set": "SOS", "base_digest": base["decision_digest"]}
    without_path = [digest | {"check": c} for c in checks]
    assert gate_lines(without_path) == (1, failures)
    with_path = [digest | {"check": c, "decision": decision} for c in checks]
    assert gate_lines(with_path) == (1, failures)
    (tmp_path / decision).parent.mkdir(parents=True)
    (tmp_path / decision).write_text("# Accepted\n", encoding="utf-8")
    assert gate_lines(with_path) == (0, [])
