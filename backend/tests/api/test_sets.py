"""The set list the app offers."""

from __future__ import annotations

from pathlib import Path

from tests.api.app_fixture import ALICE, as_user, make


def test_sets_are_listed_newest_release_first_with_their_embargo(tmp_path: Path) -> None:
    _, client, _ = make(tmp_path)
    sets = client.get("/api/sets", headers=as_user(ALICE)).json()
    codes = [s["code"] for s in sets]
    assert codes[0] == "FRA" and {"SOS", "HOB"} <= set(codes)
    dates = [s["arena_release_date"] for s in sets]
    assert dates == sorted(dates, reverse=True)
    fra = sets[0]
    assert fra["embargo_until"] == "2026-10-10" and fra["formats"] == ["bo1_sealed"]
    assert fra["usual_range"] == [78, 86]


def test_the_set_list_requires_signing_in(tmp_path: Path) -> None:
    _, client, _ = make(tmp_path)
    assert client.get("/api/sets").status_code == 401
