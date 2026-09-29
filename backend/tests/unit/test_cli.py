from __future__ import annotations

from pathlib import Path

import pytest

from arena_wizard.catalog import CARD_TABLE_DIR
from arena_wizard.cli import SyncCardsCommand, parse_args
from arena_wizard.domain.sets import packaged_set_codes


def test_sync_cards_takes_repeated_sets_case_insensitively() -> None:
    assert parse_args(["sync-cards", "--set", "sos", "--set", "HOB"]) == SyncCardsCommand(
        set_codes=("SOS", "HOB"), out_dir=CARD_TABLE_DIR
    )


def test_sync_cards_defaults_to_every_configured_set() -> None:
    assert parse_args(["sync-cards"]).set_codes == packaged_set_codes()


def test_sync_cards_accepts_an_output_directory(tmp_path: Path) -> None:
    assert parse_args(["sync-cards", "--out", str(tmp_path)]).out_dir == tmp_path


def test_a_command_is_required() -> None:
    with pytest.raises(SystemExit):
        parse_args([])
