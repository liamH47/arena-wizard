"""Pastes through the API: the CLI's checks, stored for the group in the database."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select, update
from sqlalchemy.orm import Session, sessionmaker

from arena_wizard.auth.session import SessionUser
from arena_wizard.db import repository
from arena_wizard.db.models import PasteDeletion, PasteRow
from arena_wizard.pastes.parsers import PARSER_VERSION, GradeRow
from arena_wizard.pastes.store import PasteKey, StoredPaste
from tests.api.app_fixture import ALICE, BOB, as_user, make
from tests.api.app_fixture import NOON as FIXED
from tests.unit.test_paste_commands import card_data_csv, grades_csv


@pytest.fixture
def client_sessions(tmp_path: Path) -> tuple[TestClient, sessionmaker[Session]]:
    _, client, sessions = make(tmp_path)
    return client, sessions


def _post(client: TestClient, user: Any = ALICE, **fields: Any) -> Any:
    body = {"set_code": "FRA", "dataset": "grades", "source_id": "llu-marc",
            "text": grades_csv().decode("utf-8")} | fields  # fmt: skip
    return client.post("/api/pastes", json=body, headers=as_user(user))


def test_the_registered_sources_are_listed(
    client_sessions: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _ = client_sessions
    sources = client.get("/api/pastes/sources", headers=as_user(ALICE)).json()
    ids = {s["id"] for s in sources}
    assert {"17lands-card-data", "llu-marc", "tcgplayer-lsv"} <= ids
    assert all(set(s) == {"id", "label", "dataset"} for s in sources)


def test_a_paste_is_stored_for_the_group_and_an_identical_one_changes_nothing(
    client_sessions: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, sessions = client_sessions
    first = _post(client)
    assert first.status_code == 201
    assert first.json()["messages"][0].startswith("Stored: Marc Anderson, Limited Level-Ups")
    assert "for the group" in first.json()["messages"][0]
    again = _post(client, BOB)
    assert again.status_code == 200
    assert again.json()["messages"] == [
        "Identical to today's stored paste from this source; nothing changed."
    ]
    listed = client.get("/api/pastes", params={"set_code": "fra"}, headers=as_user(BOB)).json()
    assert len(listed) == 1
    paste = listed[0]
    assert paste["key"] == f"grades/grades/llu-marc/{FIXED.date()}"
    assert paste["event_type"] is None and paste["pasted_by"] == ALICE.user_id
    assert paste["rows"] > 200 and paste["replaced_at"] is None
    with sessions() as session:
        assert len(session.scalars(select(PasteRow)).all()) == 1


def test_card_data_is_stored_with_its_event_type(
    client_sessions: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _ = client_sessions
    response = _post(
        client,
        dataset="card-data",
        source_id="17lands-card-data",
        event_type="PremierDraft",
        text=card_data_csv(draft=True).decode("utf-8"),
        copied_on=str(FIXED.date()),
        published_on=None,
        url="https://example.com/label-only",
    )
    assert response.status_code == 201
    listed = client.get("/api/pastes", params={"set_code": "FRA"}, headers=as_user(ALICE)).json()
    assert listed[0]["event_type"] == "PremierDraft"
    assert listed[0]["copied_on"] == str(FIXED.date()) and listed[0]["published_on"] is None


def test_a_published_date_is_kept(
    client_sessions: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _ = client_sessions
    _post(client, published_on="2026-09-25")
    listed = client.get("/api/pastes", params={"set_code": "FRA"}, headers=as_user(ALICE)).json()
    assert listed[0]["published_on"] == "2026-09-25"


def test_a_replaced_paste_records_when(
    client_sessions: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _ = client_sessions
    _post(client)
    assert _post(client, BOB, text=grades_csv(seed=5).decode("utf-8")).status_code == 201
    listed = client.get("/api/pastes", params={"set_code": "FRA"}, headers=as_user(ALICE)).json()
    assert listed[0]["replaced_at"] is not None and listed[0]["pasted_by"] == BOB.user_id


@pytest.mark.parametrize(
    "fields",
    [
        {"set_code": "ZZZ"},
        {"dataset": "card-data", "source_id": "17lands-card-data", "event_type": "Bogus"},
    ],
)
def test_an_unknown_set_or_event_type_is_refused(
    client_sessions: tuple[TestClient, sessionmaker[Session]], fields: dict[str, Any]
) -> None:
    client, _ = client_sessions
    response = _post(client, **fields)
    assert response.status_code == 422 and "unknown set or event type" in response.json()["detail"]


def test_a_paste_that_fails_a_check_is_refused_with_the_reason(
    client_sessions: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, sessions = client_sessions
    response = _post(client, source_id="draftsim")
    assert response.status_code == 422
    assert response.json()["detail"].startswith("Refused, nothing stored:")
    with sessions() as session:
        assert session.scalars(select(PasteRow)).all() == []


def test_a_paste_can_be_deleted_once(
    client_sessions: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, sessions = client_sessions
    _post(client, BOB)
    url = f"/api/pastes/FRA/grades/grades/llu-marc/{FIXED.date()}"
    assert client.delete(url, headers=as_user(BOB)).status_code == 204
    assert client.delete(url, headers=as_user(BOB)).status_code == 404
    with sessions() as session:
        (logged,) = session.scalars(select(PasteDeletion)).all()
    assert (logged.pasted_by, logged.deleted_by, logged.source_id) == (
        BOB.user_id,
        BOB.user_id,
        "llu-marc",
    )
    assert not hasattr(logged, "rows")


def test_another_friend_may_not_delete_a_paste_but_the_owner_may(
    client_sessions: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, sessions = client_sessions
    _post(client, BOB)
    url = f"/api/pastes/FRA/grades/grades/llu-marc/{FIXED.date()}"
    carol = SessionUser("sub-carol", "carol@example.com", "Carol")
    with sessions() as session:
        repository.upsert_user(session, carol.user_id, carol.email, carol.name, "", FIXED)
    app_settings = client.app.state.settings  # type: ignore[attr-defined]
    app_settings.allowed_emails.append(carol.email)
    refused = client.delete(url, headers=as_user(carol))
    assert refused.status_code == 403 and "whoever pasted" in refused.json()["detail"]
    with sessions() as session:
        assert len(session.scalars(select(PasteRow)).all()) == 1
        assert session.scalars(select(PasteDeletion)).all() == []
    assert client.delete(url, headers=as_user(ALICE)).status_code == 204


def test_a_paste_of_data_a_public_file_covers_is_refused_after_the_embargo(
    client_sessions: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _ = client_sessions
    response = _post(
        client,
        set_code="SOS",
        dataset="card-data",
        source_id="17lands-card-data",
        event_type="PremierDraft",
        text=card_data_csv(draft=True).decode("utf-8"),
    )
    assert response.status_code == 422 and "rule 4" in response.json()["detail"]


def test_a_paste_that_lost_a_real_race_is_a_409_and_the_winner_stays(
    client_sessions: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, sessions = client_sessions
    key = PasteKey("FRA", "grades", None, "llu-marc", FIXED.date())
    bobs = StoredPaste(
        key=key,
        label="Marc Anderson, Limited Level-Ups",
        url=None,
        copied_on=FIXED.date(),
        published_on=None,
        columns=("Tier",),
        text_sha256="d" * 64,
        parser_version=PARSER_VERSION,
        grade_rows=(GradeRow("Made-up Knight", "B", 8.0),),
    )

    def bob_wins(*_: Any) -> None:
        with sessions() as other:
            repository.save_paste(other, bobs, BOB.user_id, FIXED, None)

    # Alice's paste is checked against an empty key; Bob's commits before her insert.
    event.listen(sessions, "before_flush", bob_wins, once=True)
    response = _post(client, ALICE)
    assert response.status_code == 409 and "someone else just pasted" in response.json()["detail"]
    with sessions() as session:
        (row,) = session.scalars(select(PasteRow)).all()
        assert (row.text_sha256, row.pasted_by) == ("d" * 64, BOB.user_id)


def test_a_paste_an_older_parser_stored_is_replaced_by_pasting_it_again(
    client_sessions: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, sessions = client_sessions
    assert _post(client, ALICE).status_code == 201
    with sessions() as session:
        session.execute(update(PasteRow).values(parser_version=0))
        session.commit()
    again = _post(client, ALICE)
    assert again.status_code == 201, again.json()
    with sessions() as session:
        (row,) = session.scalars(select(PasteRow)).all()
        assert row.parser_version == PARSER_VERSION


VALID_GRADES = grades_csv().decode("utf-8")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("text", VALID_GRADES + "\u0000"),
        ("url", "javascript:alert(1)"),
        ("url", "ftp://example.com/x"),
        ("url", "https://x.example/\u0000"),
    ],
)
def test_text_the_database_cannot_hold_and_non_web_links_are_refused(
    client_sessions: tuple[TestClient, sessionmaker[Session]], field: str, value: str
) -> None:
    client, sessions = client_sessions
    response = _post(client, ALICE, **{field: value})
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", field]
    with sessions() as session:
        assert session.scalars(select(PasteRow)).all() == []
    assert _post(client, ALICE).status_code == 201


def test_a_lone_surrogate_is_refused_before_it_reaches_the_database(
    client_sessions: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, sessions = client_sessions
    body = {"set_code": "FRA", "dataset": "grades", "source_id": "llu-marc",
            "text": VALID_GRADES + "\ud800"}  # fmt: skip
    response = client.post(
        "/api/pastes",
        content=json.dumps(body),
        headers=as_user(ALICE) | {"content-type": "application/json"},
    )
    assert response.status_code == 422
    with sessions() as session:
        assert session.scalars(select(PasteRow)).all() == []


@pytest.mark.parametrize(
    "text",
    [
        "Name,Grade\nMade-up Secret Knight,B\u0000",
        "Name,Grade\nMade-up Secret Knight,B\n" + "x" * 5_000_001,
    ],
    ids=["nul", "over-length"],
)
def test_a_refused_paste_never_echoes_its_text(
    client_sessions: tuple[TestClient, sessionmaker[Session]], text: str
) -> None:
    client, _ = client_sessions
    response = _post(client, ALICE, text=text)
    assert response.status_code == 422
    assert "Made-up Secret Knight" not in response.text


@pytest.mark.parametrize(
    "path",
    [
        f"FRA/card-data/Bogus/17lands-card-data/{FIXED.date()}",
        f"FRA/grades/grades/draftsim/{FIXED.date()}",
        f"FRA/card-data/PremierDraft/17lands-card-data/{FIXED.date()}",
    ],
)
def test_deleting_an_unknown_paste_is_not_found(
    client_sessions: tuple[TestClient, sessionmaker[Session]], path: str
) -> None:
    client, _ = client_sessions
    response = client.delete(f"/api/pastes/{path}", headers=as_user(ALICE))
    assert response.status_code == 404
