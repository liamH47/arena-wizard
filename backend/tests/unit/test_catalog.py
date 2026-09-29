from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest

from arena_wizard.catalog import (
    CardTable,
    HeaderInfo,
    collector_sort_key,
    load_packaged_card_table,
    table_from_json,
    table_to_json,
    unresolved_names,
    write_card_table,
)
from arena_wizard.domain.sets import EventType
from arena_wizard.sources.scryfall import compute_card


def _table(scryfall_cards: dict[str, dict[str, Any]], header: HeaderInfo | None) -> CardTable:
    return CardTable(
        set_code="SOS",
        scryfall_queries=("set:sos",),
        header=header,
        cards=tuple(compute_card(raw) for raw in scryfall_cards.values()),
    )


def test_collector_numbers_sort_numerically_then_by_suffix() -> None:
    numbers = ["158a", "10", "158", "9", "158b", "★"]
    assert sorted(numbers, key=collector_sort_key) == ["★", "9", "10", "158", "158a", "158b"]


def test_a_table_survives_a_round_trip(scryfall_cards: dict[str, dict[str, Any]]) -> None:
    table = _table(scryfall_cards, HeaderInfo(EventType.SEALED, ("Plains", "Dáin")))
    restored = table_from_json(table_to_json(table))
    assert restored.header == table.header
    assert sorted(restored.cards, key=lambda c: c.scryfall_id) == sorted(
        table.cards, key=lambda c: c.scryfall_id
    )


def test_a_table_without_a_header_survives_a_round_trip(
    scryfall_cards: dict[str, dict[str, Any]],
) -> None:
    assert table_from_json(table_to_json(_table(scryfall_cards, None))).header is None


def test_serialization_ignores_input_order_and_keeps_non_ascii_names(
    scryfall_cards: dict[str, dict[str, Any]],
) -> None:
    table = _table(scryfall_cards, HeaderInfo(EventType.SEALED, ("Dáin",)))
    shuffled = dataclasses.replace(table, cards=tuple(reversed(table.cards)))
    text = table_to_json(table)
    assert text == table_to_json(shuffled)
    assert text.endswith("\n") and "\r" not in text
    assert "Dáin" in text


def test_an_unknown_format_version_is_refused(scryfall_cards: dict[str, dict[str, Any]]) -> None:
    document = json.loads(table_to_json(_table(scryfall_cards, None)))
    document["format_version"] = 99
    with pytest.raises(ValueError, match="99"):
        table_from_json(json.dumps(document))


def test_header_names_resolve_by_front_name_or_full_name(
    scryfall_cards: dict[str, dict[str, Any]],
) -> None:
    prepare = compute_card(scryfall_cards["prepare"])
    normal = compute_card(scryfall_cards["normal"])
    header = HeaderInfo(
        EventType.SEALED, ("Missing One", prepare.front_name, normal.name, "Missing Two")
    )
    assert unresolved_names(_table(scryfall_cards, header)) == ("Missing One", "Missing Two")


def test_a_table_without_a_header_has_nothing_unresolved(
    scryfall_cards: dict[str, dict[str, Any]],
) -> None:
    assert unresolved_names(_table(scryfall_cards, None)) == ()


def test_writing_reports_only_real_changes_and_uses_lf(
    tmp_path: Path, scryfall_cards: dict[str, dict[str, Any]]
) -> None:
    path = tmp_path / "nested" / "SOS.json"
    table = _table(scryfall_cards, None)
    assert write_card_table(table, path) is True
    assert write_card_table(table, path) is False
    assert b"\r\n" not in path.read_bytes()
    changed = dataclasses.replace(table, scryfall_queries=("set:sos", "set:soa"))
    assert write_card_table(changed, path) is True
    assert table_from_json(path.read_text(encoding="utf-8")).scryfall_queries == (
        "set:sos",
        "set:soa",
    )


def test_a_packaged_table_loads_and_a_missing_one_is_an_error() -> None:
    assert load_packaged_card_table("sos").set_code == "SOS"
    with pytest.raises(FileNotFoundError, match="XYZ"):
        load_packaged_card_table("XYZ")
