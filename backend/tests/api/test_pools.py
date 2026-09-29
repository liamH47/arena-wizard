"""Pools and builds through the API, on SQLite, with made-up users and data."""

from __future__ import annotations

import datetime as dt
import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from arena_wizard.db.models import PoolRow
from tests.api.app_fixture import (
    ALICE,
    BOB,
    Clock,
    as_user,
    create,
    fra_pool,
    make,
    paste_grades,
)
from tests.api.app_fixture import NOON as FIXED


@pytest.fixture
def app_client(tmp_path: Path) -> tuple[FastAPI, TestClient, sessionmaker[Session]]:
    return make(tmp_path)


def test_a_new_pool_is_created_and_an_identical_replay_returns_it(
    app_client: tuple[FastAPI, TestClient, sessionmaker[Session]],
) -> None:
    _, client, _ = app_client
    pool_id, text = str(uuid.uuid4()), fra_pool()
    first = create(client, pool_id=pool_id, text=text)
    assert first.status_code == 201
    body = first.json()
    assert body["id"] == pool_id and body["set_code"] == "FRA"
    assert body["nonbasic_count"] == 83 and body["usual_range"] == [78, 86]
    assert sum(e["count"] for e in body["entries"]) == 83 and body["warnings"] == []
    assert {"name", "count", "rarity", "colors", "image_uri"} <= set(body["entries"][0])
    replay = create(client, pool_id=pool_id, text=text)
    assert replay.status_code == 200 and replay.json()["id"] == pool_id


def test_a_different_body_under_an_existing_id_is_a_conflict_that_changes_nothing(
    app_client: tuple[FastAPI, TestClient, sessionmaker[Session]],
) -> None:
    _, client, sessions = app_client
    pool_id, text = str(uuid.uuid4()), fra_pool()
    create(client, pool_id=pool_id, text=text)
    assert create(client, pool_id=pool_id, text=fra_pool(seed=9)).status_code == 409
    assert create(client, BOB, pool_id=pool_id, text=text).status_code == 409
    with sessions() as session:
        row = session.get(PoolRow, pool_id)
        assert row is not None and row.raw_text == text and row.user_id == ALICE.user_id


def test_unknown_sets_and_unsupported_formats_are_refused(
    app_client: tuple[FastAPI, TestClient, sessionmaker[Session]],
) -> None:
    _, client, _ = app_client
    assert create(client, set_code="ZZZ").status_code == 422
    assert create(client, fmt="trad_sealed").status_code == 422


def test_pools_list_newest_first_and_stay_private(
    tmp_path: Path,
) -> None:
    clock = Clock()
    _, client, _ = make(tmp_path, clock=clock)
    older = create(client).json()["id"]
    clock.value = FIXED + dt.timedelta(minutes=5)
    newer = create(client).json()["id"]
    listed = client.get("/api/pools", headers=as_user(ALICE)).json()
    assert [p["id"] for p in listed] == [newer, older]
    assert client.get("/api/pools", headers=as_user(BOB)).json() == []
    assert client.get(f"/api/pools/{older}", headers=as_user(BOB)).status_code == 404
    got = client.get(f"/api/pools/{older}", headers=as_user(ALICE))
    assert got.status_code == 200 and got.json()["id"] == older


def test_the_pool_list_says_which_pools_are_built_and_hints_at_their_cards(
    tmp_path: Path,
) -> None:
    _, client, _ = make(tmp_path)
    long_name = "1 " + "A Very Long Made-up Card Name That Keeps Going" + " (FRA) 1"
    unbuilt = create(client, text="Deck\n" + long_name).json()["id"]
    built = create(client).json()["id"]
    empty = create(client, text="Deck\nSideboard").json()["id"]
    assert client.post(f"/api/pools/{built}/builds", headers=as_user(ALICE)).status_code == 201
    listed = {p["id"]: p for p in client.get("/api/pools", headers=as_user(ALICE)).json()}
    assert listed[built]["has_build"] is True
    assert listed[unbuilt]["has_build"] is False
    hint = listed[unbuilt]["hint"]
    assert hint.startswith("1 A Very Long") and hint.endswith("…") and len(hint) == 48
    assert listed[built]["hint"] == fra_pool().splitlines()[0].strip()
    assert listed[empty]["hint"] == ""
    assert client.get("/api/pools", headers=as_user(BOB)).json() == []


def test_unrecognised_lines_come_back_as_warnings(
    app_client: tuple[FastAPI, TestClient, sessionmaker[Session]],
) -> None:
    _, client, _ = app_client
    body = create(client, text=fra_pool() + "\n1 Not A Real Card (FRA) 9999").json()
    assert any(w["raw"].startswith("1 Not A Real Card") for w in body["warnings"])


def test_editing_a_pool_replaces_its_text_and_repeating_the_edit_changes_nothing(
    tmp_path: Path,
) -> None:
    clock = Clock()
    _, client, sessions = make(tmp_path, clock=clock)
    pool_id = create(client).json()["id"]
    new_text = fra_pool(seed=11)
    clock.value = FIXED + dt.timedelta(hours=1)
    edited = client.put(
        f"/api/pools/{pool_id}", json={"export_text": new_text}, headers=as_user(ALICE)
    )
    assert edited.status_code == 200 and edited.json()["export_text"] == new_text
    with sessions() as session:
        row = session.get(PoolRow, pool_id)
        assert row is not None
        first_hash, first_update = row.pool_hash, row.updated_at
    clock.value = FIXED + dt.timedelta(hours=2)
    again = client.put(
        f"/api/pools/{pool_id}", json={"export_text": new_text}, headers=as_user(ALICE)
    )
    assert again.status_code == 200
    with sessions() as session:
        row = session.get(PoolRow, pool_id)
        assert row is not None and row.pool_hash == first_hash
        assert row.updated_at == first_update
    other = client.put(
        f"/api/pools/{pool_id}", json={"export_text": new_text}, headers=as_user(BOB)
    )
    assert other.status_code == 404


def test_deleting_a_pool_removes_it_and_another_user_cannot(
    app_client: tuple[FastAPI, TestClient, sessionmaker[Session]],
) -> None:
    _, client, sessions = app_client
    pool_id = create(client).json()["id"]
    assert client.delete(f"/api/pools/{pool_id}", headers=as_user(BOB)).status_code == 404
    assert client.delete(f"/api/pools/{pool_id}", headers=as_user(ALICE)).status_code == 204
    with sessions() as session:
        assert session.scalars(select(PoolRow)).all() == []


def test_a_pool_with_a_recorded_run_cannot_be_deleted(
    app_client: tuple[FastAPI, TestClient, sessionmaker[Session]],
) -> None:
    _, client, _ = app_client
    paste_grades(client)
    pool_id = create(client).json()["id"]
    built = client.post(f"/api/pools/{pool_id}/builds", headers=as_user(ALICE)).json()
    run = {
        "id": str(uuid.uuid4()),
        "build_id": built["id"],
        "deck_index": 0,
        "wins": 3,
        "losses": 1,
    }
    assert client.post("/api/runs", json=run, headers=as_user(ALICE)).status_code == 201
    refused = client.delete(f"/api/pools/{pool_id}", headers=as_user(ALICE))
    assert refused.status_code == 409 and "recorded runs" in refused.json()["detail"]


def test_a_build_without_any_pasted_values_is_stored_with_its_refusal(
    app_client: tuple[FastAPI, TestClient, sessionmaker[Session]],
) -> None:
    _, client, _ = app_client
    pool_id = create(client).json()["id"]
    missing = client.get(f"/api/pools/{pool_id}/builds/latest", headers=as_user(ALICE))
    assert missing.status_code == 404 and "no build yet" in missing.json()["detail"]
    built = client.post(f"/api/pools/{pool_id}/builds", headers=as_user(ALICE))
    assert built.status_code == 201
    body = built.json()
    assert body["mode"] == "event" and body["decks"] == []
    assert body["refusal"].startswith("No card values for FRA")
    assert body["data_lines"][0].startswith("FRA data for this build")


def test_builds_are_reused_until_a_new_paste_changes_their_inputs(
    app_client: tuple[FastAPI, TestClient, sessionmaker[Session]],
) -> None:
    _, client, _ = app_client
    pool_id = create(client).json()["id"]
    empty = client.post(f"/api/pools/{pool_id}/builds", headers=as_user(ALICE)).json()
    assert paste_grades(client).status_code == 201
    graded = client.post(f"/api/pools/{pool_id}/builds", headers=as_user(ALICE))
    assert graded.status_code == 201
    body = graded.json()
    assert body["id"] != empty["id"] and body["refusal"] is None
    deck = body["decks"][0]
    assert deck["deck_index"] == 0 and deck["arena_list"]
    assert {"label", "terms", "spells", "lands", "values", "explanations", "toss_up"} <= set(deck)
    again = client.post(f"/api/pools/{pool_id}/builds", headers=as_user(ALICE))
    assert again.status_code == 200 and again.json()["id"] == body["id"]
    latest = client.get(f"/api/pools/{pool_id}/builds/latest", headers=as_user(ALICE))
    assert latest.json()["id"] == body["id"]
    assert paste_grades(client, seed=2).status_code == 201
    rebuilt = client.post(f"/api/pools/{pool_id}/builds", headers=as_user(ALICE))
    assert rebuilt.status_code == 201 and rebuilt.json()["id"] != body["id"]


def test_another_user_cannot_build_or_read_builds_of_a_pool(
    app_client: tuple[FastAPI, TestClient, sessionmaker[Session]],
) -> None:
    _, client, _ = app_client
    pool_id = create(client).json()["id"]
    assert client.post(f"/api/pools/{pool_id}/builds", headers=as_user(BOB)).status_code == 404
    latest = client.get(f"/api/pools/{pool_id}/builds/latest", headers=as_user(BOB))
    assert latest.status_code == 404


def test_latest_is_the_build_for_the_pool_as_it_stands_now(tmp_path: Path) -> None:
    _, client, _ = make(tmp_path)
    pool_id = create(client, ALICE, text=fra_pool(seed=5)).json()["id"]
    paste_grades(client, ALICE)
    first = client.post(f"/api/pools/{pool_id}/builds", headers=as_user(ALICE)).json()
    client.put(
        f"/api/pools/{pool_id}", json={"export_text": fra_pool(seed=6)}, headers=as_user(ALICE)
    )
    second = client.post(f"/api/pools/{pool_id}/builds", headers=as_user(ALICE)).json()
    assert second["id"] != first["id"]
    client.put(
        f"/api/pools/{pool_id}", json={"export_text": fra_pool(seed=5)}, headers=as_user(ALICE)
    )
    latest = client.get(f"/api/pools/{pool_id}/builds/latest", headers=as_user(ALICE)).json()
    assert (latest["id"], latest["current"]) == (first["id"], True)


def test_latest_is_marked_not_current_once_its_pastes_are_gone(tmp_path: Path) -> None:
    _, client, _ = make(tmp_path)
    pool_id = create(client, ALICE, text=fra_pool(seed=5)).json()["id"]
    paste_grades(client, ALICE)
    built = client.post(f"/api/pools/{pool_id}/builds", headers=as_user(ALICE)).json()
    assert built["current"] is True
    key = f"/api/pastes/FRA/grades/grades/llu-marc/{FIXED.date()}"
    assert client.delete(key, headers=as_user(ALICE)).status_code == 204
    latest = client.get(f"/api/pools/{pool_id}/builds/latest", headers=as_user(ALICE)).json()
    assert (latest["id"], latest["current"]) == (built["id"], False)


def test_a_pool_export_the_database_cannot_hold_is_refused_on_create_and_edit(
    app_client: tuple[FastAPI, TestClient, sessionmaker[Session]],
) -> None:
    _, client, sessions = app_client
    refused = create(client, text=fra_pool() + "\n1 Made-up\u0000Card (FRA) 1")
    assert refused.status_code == 422
    assert refused.json()["detail"][0]["loc"] == ["body", "export_text"]
    assert "Made-up" not in refused.text
    with sessions() as session:
        assert session.scalars(select(PoolRow)).all() == []
    created = create(client)
    pool_id, text = created.json()["id"], created.json()["export_text"]
    edit = client.put(
        f"/api/pools/{pool_id}",
        json={"export_text": text + "\u0000"},
        headers=as_user(ALICE),
    )
    assert edit.status_code == 422 and edit.json()["detail"][0]["loc"] == ["body", "export_text"]
    assert client.get(f"/api/pools/{pool_id}", headers=as_user(ALICE)).json()["export_text"] == text
