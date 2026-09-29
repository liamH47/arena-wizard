from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from arena_wizard.catalog import CARD_TABLE_DIR, load_packaged_card_table
from arena_wizard.cli import (
    BuildCommand,
    Environment,
    EvalBuildSetCommand,
    EvalRunCommand,
    LoadFileCommand,
    PasteCommand,
    PastesCommand,
    SyncCardsCommand,
    decode_text,
    parse_args,
    run,
)
from arena_wizard.datadir import DataDirError
from arena_wizard.domain.sets import EventType, Format, packaged_set_codes
from arena_wizard.etl.game_cache import file_path
from arena_wizard.eval.base import BaseUnavailable
from arena_wizard.eval.storage import EVAL_DIR
from arena_wizard.paste_commands import PasteRequest
from tests.conftest import ChunkedBody, FakeClock, make_context
from tests.seventeenlands_fixture import file_bytes
from tests.unit.test_paste_commands import grades_csv, request

PACIFIC = dt.timezone(dt.timedelta(hours=-7))
OCT_3 = dt.datetime(2026, 10, 3, 12, tzinfo=dt.UTC)


def test_sync_cards_takes_repeated_sets_case_insensitively() -> None:
    assert parse_args(["sync-cards", "--set", "sos", "--set", "HOB"]) == SyncCardsCommand(
        set_codes=("SOS", "HOB"), out_dir=CARD_TABLE_DIR
    )


def test_sync_cards_defaults_to_every_configured_set() -> None:
    command = parse_args(["sync-cards"])
    assert isinstance(command, SyncCardsCommand)
    assert command.set_codes == packaged_set_codes()


def test_sync_cards_accepts_an_output_directory(tmp_path: Path) -> None:
    command = parse_args(["sync-cards", "--out", str(tmp_path)])
    assert isinstance(command, SyncCardsCommand)
    assert command.out_dir == tmp_path


def test_a_command_is_required() -> None:
    with pytest.raises(SystemExit):
        parse_args([])


# --- parsing every command ---------------------------------------------------------------


def test_load_file_defaults_to_sealed_and_the_default_cache() -> None:
    assert parse_args(["load-file", "--set", "sos"]) == LoadFileCommand(
        "SOS", EventType.SEALED, None
    )


def test_load_file_takes_an_event_type_and_a_cache(tmp_path: Path) -> None:
    command = parse_args(
        ["load-file", "--set", "HOB", "--event-type", "PremierDraft", "--cache", str(tmp_path)]
    )
    assert command == LoadFileCommand("HOB", EventType.PREMIER_DRAFT, tmp_path)


def test_load_file_requires_a_set() -> None:
    with pytest.raises(SystemExit):
        parse_args(["load-file"])


def test_build_defaults_to_bo1_sealed_read_from_stdin() -> None:
    assert parse_args(["build", "--set", "sos"]) == BuildCommand(
        "SOS", Format.BO1_SEALED, None, None
    )


def test_build_takes_a_format_a_pool_file_and_a_cache(tmp_path: Path) -> None:
    pool = tmp_path / "pool.txt"
    command = parse_args(
        ["build", "--set", "SOS", "--format", "bo1_sealed", "--pool", str(pool)]
        + ["--cache", str(tmp_path)]
    )
    assert command == BuildCommand("SOS", Format.BO1_SEALED, pool, tmp_path)


def test_build_offers_only_formats_with_a_scoring_configuration() -> None:
    with pytest.raises(SystemExit):
        parse_args(["build", "--set", "SOS", "--format", "trad_sealed"])


def test_eval_build_set_defaults_to_sos_and_hob_with_six_hundred_pools() -> None:
    assert parse_args(["eval", "build-set"]) == EvalBuildSetCommand(
        ("SOS", "HOB"), 600, False, EVAL_DIR, None
    )


def test_eval_build_set_takes_sets_size_repin_and_directories(tmp_path: Path) -> None:
    command = parse_args(
        ["eval", "build-set", "--set", "hob", "--size", "50", "--repin"]
        + ["--eval-dir", str(tmp_path / "eval"), "--cache", str(tmp_path / "cache")]
    )
    assert command == EvalBuildSetCommand(("HOB",), 50, True, tmp_path / "eval", tmp_path / "cache")


def test_eval_run_defaults_to_writing_with_no_base() -> None:
    assert parse_args(["eval", "run"]) == EvalRunCommand(False, None, EVAL_DIR)


def test_eval_run_takes_check_base_and_directory(tmp_path: Path) -> None:
    command = parse_args(
        ["eval", "run", "--check", "--base", "origin/main", "--eval-dir", str(tmp_path)]
    )
    assert command == EvalRunCommand(True, "origin/main", tmp_path)


def test_eval_requires_a_subcommand() -> None:
    with pytest.raises(SystemExit):
        parse_args(["eval"])


# --- running commands against a fake outside world ---------------------------------------


def _offline(request: httpx.Request) -> httpx.Response:
    return httpx.Response(599)


def _bucket(request: httpx.Request) -> httpx.Response:
    headers = {"ETag": '"v1"'}
    if request.method == "HEAD":
        return httpx.Response(200, headers=headers)
    return httpx.Response(200, headers=headers, stream=ChunkedBody(file_bytes()))


def _no_base(ref: str) -> dict[str, Any] | None:
    return None


UTC_NOON = dt.datetime(2026, 9, 29, 12, tzinfo=dt.UTC)


def _refuse_data_dir() -> Path:
    raise AssertionError("this command must not touch the private data directory")


def _env(
    lines: list[str],
    handler: Callable[[httpx.Request], httpx.Response] = _offline,
    pasted: bytes = b"",
    now: dt.datetime = UTC_NOON,
    base: Callable[[str], dict[str, Any] | None] = _no_base,
    data_dir: Callable[[], Path] = _refuse_data_dir,
    read: list[Path | None] | None = None,
) -> Environment:
    def read_bytes(path: Path | None) -> bytes:
        if read is not None:
            read.append(path)
        return pasted

    return Environment(
        context=lambda: make_context(handler, FakeClock()),
        read_bytes=read_bytes,
        read_base_report=base,
        data_dir=data_dir,
        echo=lines.append,
        now=lambda: now,
    )


def test_sync_cards_with_no_sets_writes_nothing_and_succeeds(tmp_path: Path) -> None:
    lines: list[str] = []
    assert run(SyncCardsCommand((), tmp_path), _env(lines)) == 0
    assert lines == []
    assert list(tmp_path.iterdir()) == []


def test_load_file_downloads_into_the_given_cache(tmp_path: Path) -> None:
    lines: list[str] = []
    assert run(LoadFileCommand("SOS", EventType.SEALED, tmp_path), _env(lines, _bucket)) == 0
    assert lines[0].startswith("SOS Sealed: downloaded;")
    assert file_path(tmp_path, "SOS", EventType.SEALED).read_bytes() == file_bytes()


def _private(tmp_path: Path) -> Callable[[], Path]:
    return lambda: tmp_path / "private"


def test_build_without_loaded_statistics_refuses(tmp_path: Path) -> None:
    lines: list[str] = []
    read: list[Path | None] = []
    command = BuildCommand("SOS", Format.BO1_SEALED, None, tmp_path)
    env = _env(lines, pasted=b"1 Not A Card (SOS) 9999", data_dir=_private(tmp_path), read=read)
    assert run(command, env) == 1
    assert read == [None]
    assert lines[0] == "SOS pool: 0 non-basic cards (SOS pools run 81 to 85)."
    assert lines[-1].startswith("No card values for SOS")


def test_build_uses_the_injected_utc_day_for_the_embargo(tmp_path: Path) -> None:
    lines: list[str] = []
    run(LoadFileCommand("SOS", EventType.SEALED, tmp_path), _env(lines, _bucket))
    lines.clear()
    command = BuildCommand("SOS", Format.BO1_SEALED, None, tmp_path)
    evening = dt.datetime(2026, 5, 1, 17, 30, tzinfo=PACIFIC)
    run(command, _env(lines, now=evening, data_dir=_private(tmp_path)))
    assert lines[1].startswith("Statistics: 17Lands public Sealed game data")
    lines.clear()
    afternoon = dt.datetime(2026, 5, 1, 16, 59, tzinfo=PACIFIC)
    run(command, _env(lines, now=afternoon, data_dir=_private(tmp_path)))
    assert any(line.startswith("  Public file  embargoed") for line in lines)


def test_build_with_loaded_statistics_says_where_they_came_from(tmp_path: Path) -> None:
    lines: list[str] = []
    run(LoadFileCommand("SOS", EventType.SEALED, tmp_path), _env(lines, _bucket))
    lines.clear()
    run(
        BuildCommand("SOS", Format.BO1_SEALED, None, tmp_path),
        _env(lines, data_dir=_private(tmp_path)),
    )
    assert lines[1] == (
        "Statistics: 17Lands public Sealed game data, 2026-04-21 to 2026-04-22 (4 games)."
    )


def test_build_reads_the_stored_pastes_and_the_default_cache(tmp_path: Path) -> None:
    grades = PasteCommand(request(), None, tmp_path / "cache")
    env = _env([], pasted=grades_csv(), now=OCT_3, data_dir=_private(tmp_path))
    assert run(grades, env) == 0
    lines: list[str] = []
    pool = "\n".join(
        f"1 {c.name} ({c.set_code}) {c.collector_number}"
        for c in load_packaged_card_table("FRA").cards[:120]
        if not c.is_basic
    ).encode("utf-8")
    command = BuildCommand("FRA", Format.BO1_SEALED, None, None)
    assert run(command, _env(lines, pasted=pool, now=OCT_3, data_dir=_private(tmp_path))) == 0
    assert any("Marc Anderson, Limited Level-Ups, copied 2026-10-03" in line for line in lines)


def test_a_data_directory_inside_a_repository_stops_private_commands(tmp_path: Path) -> None:
    def inside() -> Path:
        raise DataDirError("inside the git work tree")

    for command in (
        BuildCommand("FRA", Format.BO1_SEALED, None, None),
        PastesCommand("FRA", None),
        PasteCommand(request(), None, None),
    ):
        lines: list[str] = []
        assert run(command, _env(lines, data_dir=inside)) == 1
        assert lines == ["inside the git work tree"]


# --- paste and pastes ----------------------------------------------------------------------


def test_paste_parses_every_flag() -> None:
    command = parse_args(
        ["paste", "--set", "fra", "--dataset", "card-data", "--source", "17lands-card-data"]
        + ["--event-type", "ArenaDirect_Sealed", "--copied-on", "2026-10-02"]
        + ["--published-on", "2026-10-01", "--url", "https://example.com/x", "--replace"]
        + ["--file", "export.csv", "--cache", "c"]
    )
    assert command == PasteCommand(
        PasteRequest(
            "FRA",
            "card-data",
            "17lands-card-data",
            EventType.ARENA_DIRECT_SEALED,
            dt.date(2026, 10, 2),
            dt.date(2026, 10, 1),
            "https://example.com/x",
            True,
        ),
        Path("export.csv"),
        Path("c"),
    )


def test_paste_has_no_default_event_type_and_reads_stdin_by_default() -> None:
    assert parse_args(["paste", "--set", "FRA", "--dataset", "grades", "--source", "llu-marc"]) == (
        PasteCommand(request(), None, None)
    )


@pytest.mark.parametrize(
    "extra",
    [
        ["--dataset", "tier-list", "--source", "llu-marc"],
        ["--dataset", "card-data", "--source", "x", "--event-type", "TradSealed"],
        ["--dataset", "grades"],
        ["--dataset", "grades", "--source", "llu-marc", "--copied-on", "yesterday"],
    ],
)
def test_paste_refuses_malformed_flags(extra: list[str]) -> None:
    with pytest.raises(SystemExit):
        parse_args(["paste", "--set", "FRA", *extra])


def test_pastes_lists_or_deletes() -> None:
    assert parse_args(["pastes", "--set", "fra"]) == PastesCommand("FRA", None)
    assert parse_args(["pastes", "--set", "FRA", "--delete", "a/b/c/d"]) == PastesCommand(
        "FRA", "a/b/c/d"
    )


def test_a_paste_is_keyed_by_the_utc_day_even_on_a_west_coast_evening(tmp_path: Path) -> None:
    lines: list[str] = []
    read: list[Path | None] = []
    evening = dt.datetime(2026, 10, 9, 23, 30, tzinfo=PACIFIC)
    command = PasteCommand(request(), Path("tiers.csv"), tmp_path / "cache")
    env = _env(lines, pasted=grades_csv(), now=evening, data_dir=_private(tmp_path), read=read)
    assert run(command, env) == 0
    assert read == [Path("tiers.csv")]
    assert "copied 2026-10-10" in lines[0]
    listed: list[str] = []
    assert run(PastesCommand("FRA", None), _env(listed, data_dir=_private(tmp_path))) == 0
    assert listed[1].startswith("  grades/grades/llu-marc/2026-10-10  ")
    deleted: list[str] = []
    key = "grades/grades/llu-marc/2026-10-10"
    assert run(PastesCommand("FRA", key), _env(deleted, data_dir=_private(tmp_path))) == 0
    assert deleted == [f"Deleted {key}."]


def test_a_paste_without_a_cache_argument_uses_the_default_cache(tmp_path: Path) -> None:
    lines: list[str] = []
    env = _env(lines, pasted=grades_csv(), now=OCT_3, data_dir=_private(tmp_path))
    assert run(PasteCommand(request(), None, None), env) == 0


def test_the_environment_day_is_the_utc_day_of_its_clock() -> None:
    env = _env([], now=dt.datetime(2026, 10, 9, 23, 30, tzinfo=PACIFIC))
    assert env.today() == dt.date(2026, 10, 10)
    default = Environment(lambda: None, lambda p: b"", lambda r: None, _refuse_data_dir)  # type: ignore[arg-type,return-value]
    assert default.now().tzinfo is not None


def test_eval_build_set_without_a_cached_file_fails(tmp_path: Path) -> None:
    lines: list[str] = []
    command = EvalBuildSetCommand(("SOS",), 600, False, tmp_path / "eval", tmp_path)
    assert run(command, _env(lines)) == 1
    assert lines == ["SOS: no cached Sealed file; run arena-wizard load-file --set SOS"]


def test_eval_run_without_a_base_never_reads_one(tmp_path: Path) -> None:
    def no_git(ref: str) -> dict[str, Any] | None:
        raise AssertionError("no base was asked for")

    lines: list[str] = []
    assert run(EvalRunCommand(False, None, tmp_path), _env(lines, base=no_git)) == 1
    assert lines == ["No pinned evaluation sets; run arena-wizard eval build-set first."]


def test_eval_run_reads_the_named_base_then_evaluates(tmp_path: Path) -> None:
    refs: list[str] = []

    def base(ref: str) -> dict[str, Any] | None:
        refs.append(ref)
        return None

    lines: list[str] = []
    assert run(EvalRunCommand(True, "origin/main", tmp_path), _env(lines, base=base)) == 1
    assert refs == ["origin/main"]
    assert lines == ["No pinned evaluation sets; run arena-wizard eval build-set first."]


def test_an_unreadable_base_fails_the_gate_closed(tmp_path: Path) -> None:
    def unreadable(ref: str) -> dict[str, Any] | None:
        raise BaseUnavailable(f"cannot read {ref}")

    lines: list[str] = []
    assert run(EvalRunCommand(True, "origin/gone", tmp_path), _env(lines, base=unreadable)) == 1
    assert lines == ["gate: cannot read origin/gone"]


# --- decoding pasted files ---------------------------------------------------------------

EXPORT = "1 Dáin, Lord of Erebor (HOB) 1\n"


def test_utf16_little_endian_with_a_byte_order_mark_decodes() -> None:
    assert decode_text(b"\xff\xfe" + EXPORT.encode("utf-16-le")) == EXPORT


def test_utf16_big_endian_with_a_byte_order_mark_decodes() -> None:
    assert decode_text(b"\xfe\xff" + EXPORT.encode("utf-16-be")) == EXPORT


def test_utf8_with_or_without_a_byte_order_mark_decodes() -> None:
    assert decode_text(EXPORT.encode("utf-8")) == EXPORT
    assert decode_text(EXPORT.encode("utf-8-sig")) == EXPORT


def test_the_windows_code_page_is_the_fallback() -> None:
    assert decode_text(EXPORT.encode("cp1252")) == EXPORT
    assert decode_text(b"\x81 is undefined in cp1252") == "� is undefined in cp1252"
