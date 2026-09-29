"""The `arena-wizard` command line.

`parse_args` is pure and `run` takes every dependency as a parameter, so both are unit
tested; `main` only wires the real network and filesystem to them.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from arena_wizard.catalog import CARD_TABLE_DIR, unresolved_names, write_card_table
from arena_wizard.domain.sets import SetConfig, load_set_config, packaged_set_codes
from arena_wizard.etl.sync_cards import compute_card_table, fetch_card_sources
from arena_wizard.sources.http import SourceContext, default_context


@dataclass(frozen=True, slots=True)
class SyncCardsCommand:
    """Regenerate the committed card tables for some sets."""

    set_codes: tuple[str, ...]
    out_dir: Path


Command = SyncCardsCommand


def parse_args(argv: Sequence[str]) -> Command:
    """Parse command-line arguments. Pure.

    Args:
        argv: The arguments after the program name.

    Returns:
        The command to run.
    """
    parser = argparse.ArgumentParser(prog="arena-wizard")
    commands = parser.add_subparsers(dest="command", required=True)
    sync = commands.add_parser("sync-cards", help="regenerate card tables from Scryfall")
    sync.add_argument(
        "--set",
        dest="sets",
        action="append",
        help="set code to sync; repeat for several (default: every configured set)",
    )
    sync.add_argument("--out", type=Path, default=CARD_TABLE_DIR, help="output directory")
    args = parser.parse_args(list(argv))
    codes = tuple(code.upper() for code in args.sets) if args.sets else packaged_set_codes()
    return SyncCardsCommand(set_codes=codes, out_dir=args.out)


def run(
    command: Command,
    ctx: SourceContext,
    *,
    load_config: Callable[[str], SetConfig] = load_set_config,
    echo: Callable[[str], None] = print,
) -> int:
    """Run a command.

    Args:
        command: What to run.
        ctx: The injected source context.
        load_config: Loads a set configuration by code.
        echo: Where progress lines go.

    Returns:
        The process exit status: 0 on success, 1 when a table has unresolved names.
    """
    status = 0
    for code in command.set_codes:
        config = load_config(code)
        table = compute_card_table(config, fetch_card_sources(ctx, config))
        changed = write_card_table(table, command.out_dir / f"{code}.json")
        header = "no 17Lands file yet" if table.header is None else table.header.event_type
        echo(
            f"{code}: {len(table.cards)} printings, header: {header}, "
            f"{'written' if changed else 'unchanged'}"
        )
        missing = unresolved_names(table)
        if missing:
            status = 1
            echo(f"{code}: {len(missing)} header names did not resolve: {', '.join(missing)}")
    return status


def main() -> None:
    """Entry point for the `arena-wizard` script."""
    sys.exit(run(parse_args(sys.argv[1:]), default_context()))
