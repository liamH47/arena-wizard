from __future__ import annotations

import copy
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest

from arena_wizard.catalog import unresolved_names
from arena_wizard.cli import SyncCardsCommand, run
from arena_wizard.domain.sets import EventType, SetConfig, parse_set_config
from arena_wizard.etl.sync_cards import compute_card_table, fetch_card_sources
from arena_wizard.sources.scryfall import NAMED_URL, SEARCH_URL
from arena_wizard.sources.seventeenlands_files import public_file_url
from tests.conftest import ChunkedBody, FakeClock, gzip_csv, make_context


def _config() -> SetConfig:
    return parse_set_config(
        {
            "code": "SOS",
            "name": "Secrets of Strixhaven",
            "arena_release_date": "2026-04-21",
            "paper_release_date": "2026-04-24",
            "formats": ["bo1_sealed"],
            "card_set_codes": ["SOS", "SPG"],
            "scryfall_queries": ["set:sos"],
            "seventeenlands_expansion": "SOS",
            "nonbasic_pool_range": [81, 85],
            "stats_sources": {"bo1_sealed": ["Sealed"]},
        }
    )


def _header_line(names: list[str]) -> str:
    return ",".join(["expansion", "won"] + [f'"deck_{n}"' for n in names])


@dataclass
class FakeWorld:
    """Scryfall and the 17Lands bucket, served from memory."""

    searches: dict[str, list[dict[str, Any]]]
    oracle_ids: dict[str, str]
    headers: dict[EventType, list[str]]
    requests: list[httpx.Request] = field(default_factory=list)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url = str(request.url)
        if url.startswith(SEARCH_URL):
            cards = self.searches.get(request.url.params["q"])
            if cards is None:
                return httpx.Response(404, json={"object": "error"})
            return httpx.Response(200, json={"object": "list", "data": cards, "has_more": False})
        if url.startswith(NAMED_URL):
            oracle_id = self.oracle_ids.get(request.url.params["exact"])
            if oracle_id is None:
                return httpx.Response(404, json={"object": "error"})
            return httpx.Response(200, json={"oracle_id": oracle_id})
        for event_type, names in self.headers.items():
            if url == public_file_url("SOS", event_type):
                body = gzip_csv([_header_line(names), "SOS,True"])
                return httpx.Response(200, stream=ChunkedBody(body))
        return httpx.Response(403)

    def named_lookups(self) -> list[str]:
        return [r.url.params["exact"] for r in self.requests if str(r.url).startswith(NAMED_URL)]


@pytest.fixture
def world(scryfall_cards: dict[str, dict[str, Any]]) -> FakeWorld:
    normal = scryfall_cards["normal"]
    prepare = scryfall_cards["prepare"]
    basic = scryfall_cards["basic"]
    guest = scryfall_cards["special_guest"]
    return FakeWorld(
        # The normal card comes back twice, as it can when two queries overlap.
        searches={
            "set:sos game:arena": [normal, prepare, basic, normal],
            f"oracleid:{guest['oracle_id']} game:arena": [guest],
        },
        oracle_ids={guest["name"]: guest["oracle_id"]},
        headers={
            EventType.SEALED: [
                basic["name"],
                normal["name"],
                prepare["card_faces"][0]["name"],
                guest["name"],
            ]
        },
    )


def test_a_header_card_outside_the_queries_is_found_by_exact_name(
    world: FakeWorld, clock: FakeClock
) -> None:
    table = compute_card_table(
        _config(), fetch_card_sources(make_context(world.handle, clock), _config())
    )
    assert unresolved_names(table) == ()
    assert sorted(card.set_code for card in table.cards) == ["SOS", "SOS", "SOS", "SPG"]
    assert world.named_lookups() == ["Archaeomancer"]


def test_a_name_scryfall_does_not_know_stays_unresolved(world: FakeWorld, clock: FakeClock) -> None:
    world.headers[EventType.SEALED].append("Ghost Card")
    table = compute_card_table(
        _config(), fetch_card_sources(make_context(world.handle, clock), _config())
    )
    assert unresolved_names(table) == ("Ghost Card",)


def test_without_a_sealed_file_the_draft_header_is_used(world: FakeWorld, clock: FakeClock) -> None:
    world.headers = {EventType.PREMIER_DRAFT: world.headers[EventType.SEALED]}
    sources = fetch_card_sources(make_context(world.handle, clock), _config())
    assert sources.header is not None
    assert sources.header.event_type is EventType.PREMIER_DRAFT


def test_before_any_file_exists_no_names_are_looked_up(world: FakeWorld, clock: FakeClock) -> None:
    world.headers = {}
    sources = fetch_card_sources(make_context(world.handle, clock), _config())
    assert sources.header is None
    assert world.named_lookups() == []
    assert len(compute_card_table(_config(), sources).cards) == 3


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_syncing_twice_rewrites_nothing_and_a_source_change_rewrites_the_table(
    world: FakeWorld, clock: FakeClock, tmp_path: Path
) -> None:
    command = SyncCardsCommand(set_codes=("SOS",), out_dir=tmp_path)
    ctx = make_context(world.handle, clock)
    lines: list[str] = []

    assert run(command, ctx, load_config=lambda code: _config(), echo=lines.append) == 0
    path = tmp_path / "SOS.json"
    first = _sha(path)
    assert "4 printings" in lines[-1] and "written" in lines[-1]

    assert run(command, ctx, load_config=lambda code: _config(), echo=lines.append) == 0
    assert _sha(path) == first
    assert lines[-1].endswith("unchanged")

    edited = copy.deepcopy(world.searches["set:sos game:arena"][0])
    edited["oracle_text"] = "Errata: this card now does something else."
    world.searches["set:sos game:arena"] = [edited, *world.searches["set:sos game:arena"][1:]]
    assert run(command, ctx, load_config=lambda code: _config(), echo=lines.append) == 0
    assert _sha(path) != first
    assert "Errata" in path.read_text(encoding="utf-8")
    assert lines[-1].endswith("written")


def test_unresolved_header_names_fail_the_command_and_are_named(
    world: FakeWorld, clock: FakeClock, tmp_path: Path
) -> None:
    world.headers[EventType.SEALED].append("Ghost Card")
    lines: list[str] = []
    status = run(
        SyncCardsCommand(set_codes=("SOS",), out_dir=tmp_path),
        make_context(world.handle, clock),
        load_config=lambda code: _config(),
        echo=lines.append,
    )
    assert status == 1
    assert lines[-1] == "SOS: 1 header names did not resolve: Ghost Card"
    assert (tmp_path / "SOS.json").is_file()


def test_a_set_with_no_file_yet_says_so(world: FakeWorld, clock: FakeClock, tmp_path: Path) -> None:
    world.headers = {}
    lines: list[str] = []
    run(
        SyncCardsCommand(set_codes=("SOS",), out_dir=tmp_path),
        make_context(world.handle, clock),
        load_config=lambda code: _config(),
        echo=lines.append,
    )
    assert "header: no 17Lands file yet" in lines[0]
