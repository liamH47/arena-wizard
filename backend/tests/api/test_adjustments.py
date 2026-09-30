"""Card adjustments through the API: shared by the group, logged, and part of the build key."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from arena_wizard.catalog import load_packaged_card_table
from arena_wizard.engine.values import spell_rarities
from tests.api.app_fixture import ALICE, BOB, as_user, create, make, paste_grades

SPELL = min(spell_rarities(load_packaged_card_table("FRA").cards))
URL = f"/api/adjustments/FRA/{SPELL}"


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    return make(tmp_path)[1]


def test_an_adjustment_is_shared_by_the_group_and_repeating_it_changes_nothing(
    client: TestClient,
) -> None:
    body = {"bomb": "add", "q_delta": 1.5, "note": "wins every game"}
    assert client.put(URL, json=body, headers=as_user(ALICE)).json() == {"changed": True}
    assert client.put(URL, json=body, headers=as_user(BOB)).json() == {"changed": False}
    (listed,) = client.get("/api/adjustments?set_code=fra", headers=as_user(BOB)).json()
    assert listed | {"updated_at": None} == body | {
        "name": SPELL,
        "by": "Alice",
        "updated_at": None,
    }
    for _ in range(2):
        assert client.delete(URL, headers=as_user(BOB)).status_code == 204
    assert client.get("/api/adjustments?set_code=FRA", headers=as_user(ALICE)).json() == []


@pytest.mark.parametrize(
    ("url", "body"),
    [
        ("/api/adjustments/XYZ/Anything", {"bomb": "add"}),
        ("/api/adjustments/FRA/Not A Card", {"bomb": "add"}),
        (URL, {}),
        (URL, {"q_delta": 0}),
        (URL, {"q_delta": 10.5}),
        (URL, {"q_delta": -10.5}),
        (URL, {"bomb": "maybe"}),
    ],
)
def test_unknown_cards_and_empty_or_out_of_range_adjustments_are_refused(
    client: TestClient, url: str, body: dict[str, Any]
) -> None:
    assert client.put(url, json=body, headers=as_user(ALICE)).status_code == 422


def test_the_largest_allowed_value_change_is_accepted(client: TestClient) -> None:
    assert client.put(URL, json={"q_delta": -10}, headers=as_user(ALICE)).status_code == 200


def test_an_adjustment_changes_the_build_and_shows_who_made_it(client: TestClient) -> None:
    pool_id = create(client).json()["id"]
    assert paste_grades(client).status_code == 201
    build = f"/api/pools/{pool_id}/builds"
    first = client.post(build, headers=as_user(ALICE)).json()
    name = first["decks"][0]["values"][0]["name"]
    body = {"q_delta": 3.0}
    assert (
        client.put(f"/api/adjustments/FRA/{name}", json=body, headers=as_user(BOB)).status_code
        == 200
    )
    rebuilt = client.post(build, headers=as_user(ALICE))
    assert rebuilt.status_code == 201
    values = {v["name"]: v for d in rebuilt.json()["decks"] for v in d["values"]}
    assert values[name]["adjustment"] == {"q_delta": 3.0, "by": "Bob"}
