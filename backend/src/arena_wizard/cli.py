"""The `arena-wizard` command line.

`parse_args` is pure and `run` takes every dependency as a parameter, so both are unit
tested; `main` only wires the real network, filesystem, stdin, and git to them.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from arena_wizard import commands, paste_commands
from arena_wizard.catalog import CARD_TABLE_DIR
from arena_wizard.datadir import DATA_DIR_ENV, DataDirError, resolve_data_dir, utc_day
from arena_wizard.devtools.floor_guard import run_git
from arena_wizard.domain.sets import (
    EventType,
    Format,
    SetConfig,
    load_set_config,
    packaged_set_codes,
)
from arena_wizard.etl.cache_paths import cache_dir
from arena_wizard.eval.base import BaseUnavailable, read_base_report
from arena_wizard.eval.storage import EVAL_DIR
from arena_wizard.paste_commands import PasteRequest
from arena_wizard.pastes.check import CARD_DATA_EVENT_TYPES
from arena_wizard.pastes.sources import DATASETS
from arena_wizard.pastes.store import read_pastes
from arena_wizard.sources.http import SourceContext, default_context


@dataclass(frozen=True, slots=True)
class SyncCardsCommand:
    """Regenerate the committed card tables for some sets."""

    set_codes: tuple[str, ...]
    out_dir: Path


@dataclass(frozen=True, slots=True)
class LoadFileCommand:
    """Download and count one 17Lands public game file into the local cache."""

    set_code: str
    event_type: EventType
    cache: Path | None


@dataclass(frozen=True, slots=True)
class BuildCommand:
    """Build decks from a pasted Arena export."""

    set_code: str
    format: Format
    pool_file: Path | None
    cache: Path | None


@dataclass(frozen=True, slots=True)
class EvalBuildSetCommand:
    """Derive the evaluation sample and pre-split counts for some sets."""

    set_codes: tuple[str, ...]
    size: int
    repin: bool
    eval_dir: Path
    cache: Path | None


@dataclass(frozen=True, slots=True)
class EvalRunCommand:
    """Evaluate the engine on the committed sample and gate against a base report."""

    check: bool
    base: str | None
    eval_dir: Path


@dataclass(frozen=True, slots=True)
class PasteCommand:
    """Store data a person exported or copied by hand (decisions 0005 and 0007)."""

    request: PasteRequest
    file: Path | None
    cache: Path | None


@dataclass(frozen=True, slots=True)
class PastesCommand:
    """List a set's stored pastes, or delete one."""

    set_code: str
    delete: str | None


Command = (
    SyncCardsCommand
    | LoadFileCommand
    | BuildCommand
    | EvalBuildSetCommand
    | EvalRunCommand
    | PasteCommand
    | PastesCommand
)

PASTE_HELP = (
    "store data you exported or copied by hand. Decision 0005: by hand only. Never pipe a "
    "script, a scraper, or an automated download into this command."
)


def _codes(values: list[str] | None, default: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(v.upper() for v in values) if values else default


def parse_args(argv: Sequence[str]) -> Command:
    """Parse command-line arguments. Pure.

    Args:
        argv: The arguments after the program name.

    Returns:
        The command to run.
    """
    parser = argparse.ArgumentParser(prog="arena-wizard")
    sub = parser.add_subparsers(dest="command", required=True)

    sync = sub.add_parser("sync-cards", help="regenerate card tables from Scryfall")
    sync.add_argument("--set", dest="sets", action="append", help="repeatable; default all")
    sync.add_argument("--out", type=Path, default=CARD_TABLE_DIR)

    load = sub.add_parser("load-file", help="download and count a 17Lands game file")
    load.add_argument("--set", required=True)
    load.add_argument(
        "--event-type", default=EventType.SEALED.value, choices=[e.value for e in EventType]
    )
    load.add_argument("--cache", type=Path, default=None)

    build = sub.add_parser("build", help="build decks from an Arena export (stdin or --pool)")
    build.add_argument("--set", required=True)
    # Only formats with a scoring configuration are offered.
    build.add_argument(
        "--format", default=Format.BO1_SEALED.value, choices=[Format.BO1_SEALED.value]
    )
    build.add_argument("--pool", type=Path, default=None, help="file with the export text")
    build.add_argument("--cache", type=Path, default=None)

    paste = sub.add_parser("paste", help=PASTE_HELP, description=PASTE_HELP)
    paste.add_argument("--set", required=True)
    paste.add_argument("--dataset", required=True, choices=list(DATASETS))
    paste.add_argument("--source", required=True, help="a source id, e.g. llu-marc or own-liam")
    paste.add_argument(
        "--event-type",
        default=None,
        choices=[e.value for e in CARD_DATA_EVENT_TYPES],
        help="required for card-data; no default",
    )
    paste.add_argument("--copied-on", type=dt.date.fromisoformat, default=None)
    paste.add_argument("--published-on", type=dt.date.fromisoformat, default=None)
    paste.add_argument("--url", default=None, help="a label only; never fetched")
    paste.add_argument("--replace", action="store_true", help="allow a much smaller paste")
    paste.add_argument("--file", type=Path, default=None, help="the exported file; else stdin")
    paste.add_argument("--cache", type=Path, default=None)

    pastes = sub.add_parser("pastes", help="list a set's stored pastes, or delete one")
    pastes.add_argument("--set", required=True)
    pastes.add_argument("--delete", default=None, help="a key as `pastes` prints it")

    evaluate = sub.add_parser("eval", help="the evaluation harness")
    eval_sub = evaluate.add_subparsers(dest="eval_command", required=True)
    build_set = eval_sub.add_parser("build-set", help="derive the sample from cached files")
    build_set.add_argument("--set", dest="sets", action="append")
    build_set.add_argument("--size", type=int, default=600)
    build_set.add_argument("--repin", action="store_true")
    build_set.add_argument("--eval-dir", type=Path, default=EVAL_DIR)
    build_set.add_argument("--cache", type=Path, default=None)
    run = eval_sub.add_parser("run", help="evaluate the engine and gate the result")
    run.add_argument("--check", action="store_true", help="compare, do not write")
    run.add_argument("--base", default=None, help="git ref whose report is the gate's base")
    run.add_argument("--eval-dir", type=Path, default=EVAL_DIR)

    args = parser.parse_args(list(argv))
    if args.command == "sync-cards":
        return SyncCardsCommand(_codes(args.sets, packaged_set_codes()), args.out)
    if args.command == "load-file":
        return LoadFileCommand(args.set.upper(), EventType(args.event_type), args.cache)
    if args.command == "build":
        return BuildCommand(args.set.upper(), Format(args.format), args.pool, args.cache)
    if args.command == "paste":
        request = PasteRequest(
            set_code=args.set.upper(),
            dataset=args.dataset,
            source_id=args.source,
            event_type=EventType(args.event_type) if args.event_type else None,
            copied_on=args.copied_on,
            published_on=args.published_on,
            url=args.url,
            replace=args.replace,
        )
        return PasteCommand(request, args.file, args.cache)
    if args.command == "pastes":
        return PastesCommand(args.set.upper(), args.delete)
    if args.eval_command == "build-set":
        return EvalBuildSetCommand(
            _codes(args.sets, ("SOS", "HOB")), args.size, args.repin, args.eval_dir, args.cache
        )
    return EvalRunCommand(args.check, args.base, args.eval_dir)


@dataclass(frozen=True, slots=True)
class Environment:
    """The outside world, injected so every command is testable."""

    context: Callable[[], SourceContext]
    read_bytes: Callable[[Path | None], bytes]
    read_base_report: Callable[[str], dict[str, Any] | None]
    data_dir: Callable[[], Path]
    echo: Callable[[str], None] = print
    now: Callable[[], dt.datetime] = lambda: dt.datetime.now(dt.UTC)
    load_config: Callable[[str], SetConfig] = load_set_config

    def today(self) -> dt.date:
        """The UTC day: the paste key and the embargo both count in UTC (decision 0007)."""
        return utc_day(self.now())


def run(command: Command, env: Environment) -> int:
    """Run a command and return the process exit status."""
    if isinstance(command, SyncCardsCommand):
        return commands.sync_cards(
            command.set_codes, command.out_dir, env.context(), env.load_config, env.echo
        )
    if isinstance(command, LoadFileCommand):
        return commands.load_game_file(
            command.set_code, command.event_type, env.context(), command.cache, env.echo
        )
    if isinstance(command, BuildCommand | PasteCommand | PastesCommand):
        try:
            data_dir = env.data_dir()
        except DataDirError as error:
            env.echo(str(error))
            return 1
        return _run_private(command, data_dir, env)
    if isinstance(command, EvalBuildSetCommand):
        return commands.build_eval_set(
            command.set_codes,
            command.size,
            command.repin,
            command.eval_dir,
            command.cache,
            env.echo,
        )
    try:
        base = env.read_base_report(command.base) if command.base else None
    except BaseUnavailable as error:
        env.echo(f"gate: {error}")
        return 1
    return commands.run_eval(command.eval_dir, command.check, base, env.echo)


def _run_private(
    command: BuildCommand | PasteCommand | PastesCommand, data_dir: Path, env: Environment
) -> int:
    """Run a command that reads or writes the private data directory."""
    if isinstance(command, PastesCommand):
        if command.delete is not None:
            return paste_commands.delete(command.set_code, command.delete, data_dir, env.echo)
        return paste_commands.list_pastes(command.set_code, data_dir, env.echo)
    today = env.today()
    if isinstance(command, PasteCommand):
        config = env.load_config(command.request.set_code)
        return paste_commands.paste(
            command.request,
            env.read_bytes(command.file),
            config,
            data_dir,
            command.cache or cache_dir(),
            today,
            decode_text,
            env.echo,
        )
    config = env.load_config(command.set_code)
    pastes, stale = read_pastes(data_dir, command.set_code)
    data = commands.BuildData(
        public_sealed=commands.statistics_for(command.set_code, command.cache),
        public_draft=commands.statistics_for(
            command.set_code, command.cache, EventType.PREMIER_DRAFT
        ),
        pastes=pastes,
        stale=stale,
        covered=paste_commands.covered_event_types(config, command.cache or cache_dir(), today),
    )
    return commands.build(
        command.set_code,
        command.format,
        decode_text(env.read_bytes(command.pool_file)),
        data,
        today,
        env.echo,
    )


def decode_text(data: bytes) -> str:
    """Decode a pasted export whatever Windows tool saved it. Pure.

    PowerShell's `>` writes UTF-16 with a byte-order mark and `Set-Content` writes the
    ANSI code page; a mangled accented name costs nothing because lines resolve by set
    code and collector number first.
    """
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def main() -> None:
    """Entry point for the `arena-wizard` script."""

    def read_bytes(path: Path | None) -> bytes:
        # Bytes, not text: the console code page would garble names and keep a BOM.
        return path.read_bytes() if path else sys.stdin.buffer.read()

    def data_dir() -> Path:
        return resolve_data_dir(os.environ.get(DATA_DIR_ENV), Path.home())

    def read_base(ref: str) -> dict[str, Any] | None:
        root = Path(run_git(Path.cwd(), "rev-parse", "--show-toplevel").stdout.strip())
        return read_base_report(root, ref)

    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    env = Environment(default_context, read_bytes, read_base, data_dir)
    sys.exit(run(parse_args(sys.argv[1:]), env))
