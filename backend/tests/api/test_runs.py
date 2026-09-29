"""Recorded runs through the API: retry-safe creates, edits that stick, privacy."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.api.app_fixture import ALICE, BOB, as_user, create, make, paste_grades


@pytest.fixture
def built(tmp_path: Path) -> tuple[TestClient, int]:
    """A client and the id of a build with decks, owned by Alice."""
    _, client, _ = make(tmp_path)
    paste_grades(client)
    pool_id = create(client).json()["id"]
    build = client.post(f"/api/pools/{pool_id}/builds", headers=as_user(ALICE)).json()
    return client, build["id"]


def _run(build_id: int, **fields: Any) -> dict[str, Any]:
    body = {"id": str(uuid.uuid4()), "build_id": build_id, "deck_index": 0, "wins": 3,
            "losses": 1, "event_name": "FRA Arena Direct", "notes": "made-up"}  # fmt: skip
    return body | fields


def test_a_run_is_recorded_and_an_identical_replay_returns_it(
    built: tuple[TestClient, int],
) -> None:
    client, build_id = built
    body = _run(build_id)
    first = client.post("/api/runs", json=body, headers=as_user(ALICE))
    assert first.status_code == 201
    assert first.json()["wins"] == 3 and first.json()["event_name"] == "FRA Arena Direct"
    replay = client.post("/api/runs", json=body, headers=as_user(ALICE))
    assert replay.status_code == 200 and replay.json()["id"] == body["id"]
    listed = client.get("/api/runs", headers=as_user(ALICE)).json()
    assert [r["id"] for r in listed] == [body["id"]]
    assert client.get("/api/runs", headers=as_user(BOB)).json() == []


def test_an_edit_survives_a_replayed_create(built: tuple[TestClient, int]) -> None:
    client, build_id = built
    body = _run(build_id)
    client.post("/api/runs", json=body, headers=as_user(ALICE))
    patched = client.patch(f"/api/runs/{body['id']}", json={"wins": 4}, headers=as_user(ALICE))
    assert patched.status_code == 200 and patched.json()["wins"] == 4
    replay = client.post("/api/runs", json=body, headers=as_user(ALICE))
    assert replay.status_code == 200 and replay.json()["wins"] == 4
    unchanged = client.patch(
        f"/api/runs/{body['id']}", json={"wins": 4, "losses": 1}, headers=as_user(ALICE)
    )
    assert unchanged.json()["updated_at"] == patched.json()["updated_at"]


def test_a_different_body_or_another_user_under_the_same_id_is_a_conflict(
    built: tuple[TestClient, int],
) -> None:
    client, build_id = built
    body = _run(build_id)
    client.post("/api/runs", json=body, headers=as_user(ALICE))
    changed = client.post("/api/runs", json=body | {"wins": 5}, headers=as_user(ALICE))
    assert changed.status_code == 409
    assert client.post("/api/runs", json=body, headers=as_user(BOB)).status_code == 409


def test_a_run_against_another_user_s_deck_or_a_missing_deck_is_not_found(
    built: tuple[TestClient, int],
) -> None:
    client, build_id = built
    assert client.post("/api/runs", json=_run(build_id), headers=as_user(BOB)).status_code == 404
    missing = _run(build_id, deck_index=99)
    assert client.post("/api/runs", json=missing, headers=as_user(ALICE)).status_code == 404


def test_only_the_owner_can_edit_or_delete_a_run(built: tuple[TestClient, int]) -> None:
    client, build_id = built
    body = _run(build_id)
    client.post("/api/runs", json=body, headers=as_user(ALICE))
    url = f"/api/runs/{body['id']}"
    assert client.patch(url, json={"wins": 7}, headers=as_user(BOB)).status_code == 404
    assert client.delete(url, headers=as_user(BOB)).status_code == 404
    assert client.delete(url, headers=as_user(ALICE)).status_code == 204
    assert client.delete(url, headers=as_user(ALICE)).status_code == 404


def test_impossible_records_are_rejected(built: tuple[TestClient, int]) -> None:
    client, build_id = built
    negative = client.post("/api/runs", json=_run(build_id, wins=-1), headers=as_user(ALICE))
    assert negative.status_code == 422


@pytest.mark.parametrize("field", ["notes", "event_name"])
def test_a_run_with_text_the_database_cannot_hold_is_refused(
    built: tuple[TestClient, int], field: str
) -> None:
    client, build_id = built
    body = _run(build_id, **{field: "made-up\u0000note"})
    response = client.post("/api/runs", json=body, headers=as_user(ALICE))
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", field]
    assert client.get("/api/runs", headers=as_user(ALICE)).json() == []


def test_run_ids_beyond_what_the_database_holds_are_refused(built: tuple[TestClient, int]) -> None:
    client, build_id = built
    for fields in ({"build_id": 2**31}, {"deck_index": 2**31}):
        response = client.post("/api/runs", json=_run(build_id) | fields, headers=as_user(ALICE))
        assert response.status_code == 422
        assert response.json()["detail"][0]["loc"] == ["body", *fields]
