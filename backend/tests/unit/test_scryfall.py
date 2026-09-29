from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from arena_wizard.domain.cards import Color, Rarity, sort_colors
from arena_wizard.sources.http import SourceError
from arena_wizard.sources.scryfall import (
    NAMED_URL,
    SEARCH_URL,
    compute_card,
    fetch_oracle_id,
    fetch_search,
)
from tests.conftest import FakeClock, make_context

# --- compute_card: pure conversion of real Scryfall objects ------------------------------


def test_a_normal_card_keeps_its_printed_characteristics(
    scryfall_cards: dict[str, dict[str, Any]],
) -> None:
    raw = scryfall_cards["normal"]
    card = compute_card(raw)
    assert card.name == card.front_name == raw["name"]
    assert card.set_code == "SOS"
    assert card.rarity is Rarity.COMMON
    assert card.mana_cost == raw["mana_cost"]
    assert card.mana_value == raw["cmc"]
    assert card.power == raw["power"]
    assert card.faces == ()
    assert card.arena_id == raw["arena_id"]
    assert "?" in raw["image_uris"]["normal"]
    assert card.image_uri == raw["image_uris"]["normal"].split("?")[0]
    assert not card.is_basic


@pytest.mark.parametrize("layout", ["prepare", "adventure"])
def test_a_two_part_card_is_keyed_by_its_front_face_name(
    scryfall_cards: dict[str, dict[str, Any]], layout: str
) -> None:
    raw = scryfall_cards[layout]
    card = compute_card(raw)
    assert " // " in card.name
    assert card.front_name == raw["card_faces"][0]["name"]
    assert card.name.startswith(card.front_name)
    assert [face.name for face in card.faces] == [f["name"] for f in raw["card_faces"]]
    assert card.mana_cost == raw["mana_cost"]


def test_a_transform_card_rebuilds_fields_scryfall_only_puts_on_its_faces(
    scryfall_cards: dict[str, dict[str, Any]],
) -> None:
    raw = scryfall_cards["transform"]
    assert "mana_cost" not in raw and "colors" not in raw and "image_uris" not in raw
    card = compute_card(raw)
    front, back = raw["card_faces"]
    assert card.mana_cost == f"{front['mana_cost']} // {back['mana_cost']}"
    assert card.oracle_text == f"{front['oracle_text']}\n//\n{back['oracle_text']}"
    assert card.colors == sort_colors([Color(c) for c in front["colors"] + back["colors"]])
    assert card.image_uri == front["image_uris"]["normal"].split("?")[0]
    assert card.power == front["power"]


def test_a_special_guest_without_an_arena_id_still_converts(
    scryfall_cards: dict[str, dict[str, Any]],
) -> None:
    card = compute_card(scryfall_cards["special_guest"])
    assert card.set_code == "SPG"
    assert card.arena_id is None


def test_a_hybrid_card_lists_both_colors_in_wubrg_order(
    scryfall_cards: dict[str, dict[str, Any]],
) -> None:
    card = compute_card(scryfall_cards["hybrid_no_arena_id"])
    assert card.colors == (Color.WHITE, Color.BLACK)
    assert card.arena_id is None


def test_a_basic_land_is_recognised(scryfall_cards: dict[str, dict[str, Any]]) -> None:
    card = compute_card(scryfall_cards["basic"])
    assert card.is_basic
    assert card.produced_mana == ("W",)


def test_sort_colors_dedupes_and_orders_wubrg() -> None:
    assert sort_colors([Color.GREEN, Color.WHITE, Color.GREEN, Color.BLUE]) == (
        Color.WHITE,
        Color.BLUE,
        Color.GREEN,
    )


# --- fetch_search: pagination and failure handling ---------------------------------------


def _page(cards: list[dict[str, Any]], next_page: str | None, total: int = 3) -> httpx.Response:
    body: dict[str, Any] = {
        "object": "list",
        "data": cards,
        "has_more": next_page is not None,
        "total_cards": total,
    }
    if next_page is not None:
        body["next_page"] = next_page
    return httpx.Response(200, json=body)


def test_search_follows_every_page_and_restricts_to_arena(clock: FakeClock) -> None:
    requests: list[httpx.Request] = []
    page_two = f"{SEARCH_URL}?page=2&q=set%3Asos+game%3Aarena"

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if "page=2" in str(request.url):
            return _page([{"id": "c"}], None)
        return _page([{"id": "a"}, {"id": "b"}], page_two)

    cards = fetch_search(make_context(handler, clock), "set:sos")
    assert [c["id"] for c in cards] == ["a", "b", "c"]
    first = parse_qs(urlparse(str(requests[0].url)).query)
    assert first["q"] == ["set:sos game:arena"]
    assert first["unique"] == ["prints"]
    assert clock.sleeps == [pytest.approx(0.5)]


def test_a_result_set_that_changed_between_pages_is_an_error(clock: FakeClock) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "page=2" in str(request.url):
            return _page([{"id": "c"}], None, total=4)
        return _page([{"id": "a"}, {"id": "b"}], f"{SEARCH_URL}?page=2", total=4)

    with pytest.raises(SourceError, match="returned 3 cards but reported 4"):
        fetch_search(make_context(handler, clock), "set:sos")


def test_a_query_matching_nothing_is_an_empty_list(clock: FakeClock) -> None:
    ctx = make_context(lambda request: httpx.Response(404, json={"object": "error"}), clock)
    assert fetch_search(ctx, "set:nothing") == []


@pytest.mark.parametrize("failing_page", [1, 2])
def test_a_server_error_on_any_page_raises(clock: FakeClock, failing_page: int) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        page = 2 if "page=2" in str(request.url) else 1
        if page == failing_page:
            return httpx.Response(500)
        return _page([{"id": "a"}], f"{SEARCH_URL}?page=2")

    with pytest.raises(SourceError, match="500"):
        fetch_search(make_context(handler, clock), "set:sos")


def test_a_response_without_the_list_shape_raises(clock: FakeClock) -> None:
    ctx = make_context(lambda request: httpx.Response(200, json={"object": "list"}), clock)
    with pytest.raises(SourceError, match="lacks"):
        fetch_search(ctx, "set:sos")


# --- fetch_oracle_id -----------------------------------------------------------------------


def test_named_lookup_returns_the_oracle_id(clock: FakeClock) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url).startswith(NAMED_URL)
        assert request.url.params["exact"] == "Archaeomancer"
        return httpx.Response(200, json={"oracle_id": "oid-1"})

    assert fetch_oracle_id(make_context(handler, clock), "Archaeomancer") == "oid-1"


def test_named_lookup_of_an_unknown_name_is_none(clock: FakeClock) -> None:
    ctx = make_context(lambda request: httpx.Response(404), clock)
    assert fetch_oracle_id(ctx, "Not A Card") is None


@pytest.mark.parametrize(
    "response",
    [httpx.Response(502), httpx.Response(200, json={"name": "no oracle id"})],
)
def test_named_lookup_failures_raise(clock: FakeClock, response: httpx.Response) -> None:
    with pytest.raises(SourceError):
        fetch_oracle_id(make_context(lambda request: response, clock), "Anything")
