from __future__ import annotations

import datetime as dt
from typing import Any

import pytest

from arena_wizard.domain.sets import (
    ConfigError,
    EventType,
    Format,
    load_set_config,
    packaged_set_codes,
    parse_set_config,
)


def _valid() -> dict[str, Any]:
    return {
        "code": "SOS",
        "name": "Secrets of Strixhaven",
        "arena_release_date": dt.date(2026, 4, 21),
        "paper_release_date": "2026-04-24",
        "formats": ["bo1_sealed"],
        "card_set_codes": ["SOS", "SOA", "SPG"],
        "scryfall_queries": ["set:sos"],
        "seventeenlands_expansion": "SOS",
        "nonbasic_pool_range": [81, 85],
        "stats_sources": {"bo1_sealed": ["Sealed", "ArenaDirect_Sealed", "PremierDraft"]},
    }


def test_a_valid_mapping_parses_with_dates_from_yaml_or_strings() -> None:
    config = parse_set_config(_valid())
    assert config.arena_release_date == dt.date(2026, 4, 21)
    assert config.paper_release_date == dt.date(2026, 4, 24)
    assert config.formats == (Format.BO1_SEALED,)
    assert config.stats_sources[Format.BO1_SEALED][0] is EventType.SEALED
    assert config.nonbasic_pool_range == (81, 85)


def test_the_embargo_lifts_on_the_twelfth_day_on_arena() -> None:
    assert load_set_config("fra").embargo_until == dt.date(2026, 10, 10)


@pytest.mark.parametrize(
    "field",
    [
        "code",
        "name",
        "arena_release_date",
        "paper_release_date",
        "formats",
        "card_set_codes",
        "scryfall_queries",
        "seventeenlands_expansion",
        "nonbasic_pool_range",
        "stats_sources",
    ],
)
def test_a_missing_field_is_named_in_the_error(field: str) -> None:
    raw = _valid()
    del raw[field]
    with pytest.raises(ConfigError, match=field):
        parse_set_config(raw)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("arena_release_date", "April 21", "not an ISO date"),
        ("nonbasic_pool_range", [85, 81], "nonbasic_pool_range"),
        ("nonbasic_pool_range", [81], "nonbasic_pool_range"),
        ("nonbasic_pool_range", "81-85", "nonbasic_pool_range"),
        ("nonbasic_pool_range", [81, "85"], "nonbasic_pool_range"),
        ("stats_sources", {}, "stats_sources"),
        ("stats_sources", ["Sealed"], "stats_sources"),
        ("stats_sources", {"bo1_sealed": []}, "stats_sources.bo1_sealed"),
        ("stats_sources", {"bo1_sealed": ["Sealedd"]}, "unknown format or event type"),
        ("stats_sources", {"bo3_sealed": ["Sealed"]}, "unknown format or event type"),
        ("formats", "bo1_sealed", "formats"),
        ("formats", ["cube"], "unknown format or event type"),
        ("card_set_codes", [], "card_set_codes"),
        ("scryfall_queries", ["set:sos", 3], "scryfall_queries"),
    ],
)
def test_a_malformed_field_is_named_in_the_error(field: str, value: Any, message: str) -> None:
    raw = _valid()
    raw[field] = value
    with pytest.raises(ConfigError, match=message):
        parse_set_config(raw)


def test_every_packaged_set_loads() -> None:
    assert packaged_set_codes() == ("FRA", "HOB", "SOS")
    for code in packaged_set_codes():
        assert load_set_config(code).code == code


def test_an_unknown_set_is_a_config_error() -> None:
    with pytest.raises(ConfigError, match="no set configuration for 'XYZ'"):
        load_set_config("XYZ")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, ()),
        ([], ()),
        (["Sealed", "PremierDraft"], (EventType.SEALED, EventType.PREMIER_DRAFT)),
    ],
)
def test_published_public_files_are_optional(raw: Any, expected: tuple[EventType, ...]) -> None:
    values = _valid() if raw is None else _valid() | {"public_files": raw}
    assert parse_set_config(values).public_files == expected


def test_an_unknown_public_file_event_type_is_refused() -> None:
    with pytest.raises(ConfigError, match="public_files has an unknown event type"):
        parse_set_config(_valid() | {"public_files": ["Cube"]})


def test_a_public_files_value_that_is_not_a_list_of_strings_is_refused() -> None:
    with pytest.raises(ConfigError, match="public_files"):
        parse_set_config(_valid() | {"public_files": "Sealed"})


def test_sos_and_hob_record_their_published_files_and_fra_none() -> None:
    assert load_set_config("SOS").public_files == (EventType.SEALED, EventType.PREMIER_DRAFT)
    assert load_set_config("HOB").public_files == (EventType.SEALED, EventType.PREMIER_DRAFT)
    assert load_set_config("FRA").public_files == ()
