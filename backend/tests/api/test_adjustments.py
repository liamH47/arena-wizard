"""Card adjustments through the API: shared by the group, logged, and part of the build key."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from arena_wizard.catalog import load_packaged_card_table
from arena_wizard.engine.values import spell_rarities
from tests.api.app_fixture import ALICE, BOB, as_user, create, fra_pool, make, paste_grades

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


def test_a_value_change_is_kept_to_one_decimal_and_one_that_rounds_to_zero_is_refused(
    client: TestClient,
) -> None:
    assert client.put(URL, json={"q_delta": 1e-12}, headers=as_user(ALICE)).status_code == 422
    client.put(URL, json={"q_delta": 1.26}, headers=as_user(ALICE))
    (listed,) = client.get("/api/adjustments?set_code=FRA", headers=as_user(ALICE)).json()
    assert listed["q_delta"] == 1.3


def test_only_adjustments_to_the_pools_cards_change_its_build(client: TestClient) -> None:
    pool_id = create(client).json()["id"]
    assert paste_grades(client).status_code == 201
    build = f"/api/pools/{pool_id}/builds"
    first = client.post(build, headers=as_user(ALICE)).json()
    deck = first["decks"][0]
    name = deck["spells"][0]["name"]
    outside = next(n for n in sorted(spell_rarities(load_packaged_card_table("FRA").cards))
                   if n not in fra_pool())  # fmt: skip
    adjust = f"/api/adjustments/FRA/{name}"

    client.put(f"/api/adjustments/FRA/{outside}", json={"bomb": "add"}, headers=as_user(BOB))
    assert client.post(build, headers=as_user(ALICE)).json()["id"] == first["id"]

    client.put(adjust, json={"bomb": "add", "q_delta": 3.0}, headers=as_user(BOB))
    rebuilt = client.post(build, headers=as_user(ALICE))
    assert rebuilt.status_code == 201
    body = rebuilt.json()
    values = {v["name"]: v for d in body["decks"] for v in d["values"]}
    assert values[name]["adjustment"] == {"q_delta": 3.0, "by": "Bob"}
    assert any(f"{name} (added by Bob)" in s for d in body["decks"] for s in d["explanations"])
    assert any(line.startswith("  Adjusted     used     1 of") for line in body["data_lines"])

    note = {"bomb": "add", "q_delta": 3.0, "note": "typo fixed"}
    client.put(adjust, json=note, headers=as_user(ALICE))
    assert client.post(build, headers=as_user(ALICE)).json()["id"] == body["id"]

    client.delete(adjust, headers=as_user(BOB))
    assert client.post(build, headers=as_user(ALICE)).json()["id"] == first["id"]
