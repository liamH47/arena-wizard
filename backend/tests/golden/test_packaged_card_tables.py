"""The committed card tables, checked without the network.

These guard the promise the resolver depends on: every card 17Lands has recorded for a
set can be found in that set's table, and every printing in a table carries a set code an
export line from that set's packs can show.
"""

from __future__ import annotations

from importlib import resources

import pytest

from arena_wizard.catalog import load_packaged_card_table, table_to_json, unresolved_names
from arena_wizard.domain.sets import load_set_config, packaged_set_codes


@pytest.mark.parametrize("code", packaged_set_codes())
def test_every_configured_set_has_a_card_table(code: str) -> None:
    table = load_packaged_card_table(code)
    assert table.set_code == code
    assert table.cards


@pytest.mark.parametrize("code", packaged_set_codes())
def test_every_17lands_header_name_resolves(code: str) -> None:
    assert unresolved_names(load_packaged_card_table(code)) == ()


@pytest.mark.parametrize("code", packaged_set_codes())
def test_every_printing_carries_one_of_the_sets_export_codes(code: str) -> None:
    allowed = set(load_set_config(code).card_set_codes)
    assert {card.set_code for card in load_packaged_card_table(code).cards} <= allowed


@pytest.mark.parametrize("code", packaged_set_codes())
def test_the_file_on_disk_is_exactly_what_the_serializer_writes(code: str) -> None:
    path = resources.files("arena_wizard").joinpath("data", "cards", f"{code}.json")
    assert path.read_text(encoding="utf-8") == table_to_json(load_packaged_card_table(code))


# Header sizes recorded when the tables were generated (2026-09-28). A shorter header
# would make "every name resolves" trivially true, so the size itself is pinned.
RECORDED_SEALED_HEADER_SIZES = {"SOS": 346, "HOB": 193}


@pytest.mark.parametrize(("code", "size"), sorted(RECORDED_SEALED_HEADER_SIZES.items()))
def test_the_mature_sets_are_checked_against_their_full_sealed_header(code: str, size: int) -> None:
    header = load_packaged_card_table(code).header
    assert header is not None and header.event_type == "Sealed"
    assert len(header.names) == size


def test_reality_fracture_has_no_header_until_17lands_publishes_a_file() -> None:
    # When this fails, 17Lands has published FRA data: re-run sync-cards for FRA, pin its
    # header size above, and remove the FRA entries from docs/known-broken.md.
    assert load_packaged_card_table("FRA").header is None


def test_every_set_other_than_reality_fracture_has_a_pinned_header_size() -> None:
    assert set(packaged_set_codes()) - {"FRA"} == set(RECORDED_SEALED_HEADER_SIZES)


def test_strixhaven_includes_its_bonus_sheet_and_exactly_its_ten_special_guests() -> None:
    cards = load_packaged_card_table("SOS").cards
    guests = sorted(card.collector_number for card in cards if card.set_code == "SPG")
    assert len(guests) == 10
    assert guests[0] == "149" and guests[-1] == "158a"
    assert any(card.set_code == "SOA" for card in cards)
