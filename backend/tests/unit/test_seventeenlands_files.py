from __future__ import annotations

import gzip
import random

import httpx
import pytest

from arena_wizard.domain.sets import EventType
from arena_wizard.sources.http import SourceError
from arena_wizard.sources.seventeenlands_files import (
    fetch_card_names,
    first_line,
    parse_card_names,
    public_file_url,
)
from tests.conftest import ChunkedBody, FakeClock, gzip_csv, make_context

# Copied from the real SOS Sealed header shape: metadata columns, then the card families.
HEADER = (
    "expansion,event_type,draft_id,won,"
    'deck_Plains,"deck_Abigale, Poet Laureate",deck_Archaeomancer,'
    'sideboard_Plains,"sideboard_Abigale, Poet Laureate",sideboard_Archaeomancer,'
    'drawn_Plains,"drawn_Abigale, Poet Laureate",drawn_Archaeomancer'
)
ROW = "SOS,Sealed,abc,True,14,1,0,0,0,1,2,0,0"


def _chunks(data: bytes, size: int) -> list[bytes]:
    return [data[i : i + size] for i in range(0, len(data), size)]


def test_public_file_url_names_the_expansion_and_event_type() -> None:
    assert public_file_url("SOS", EventType.SEALED) == (
        "https://17lands-public.s3.amazonaws.com/analysis_data/game_data/"
        "game_data_public.SOS.Sealed.csv.gz"
    )


def test_first_line_stops_at_the_header_even_in_one_byte_chunks() -> None:
    assert first_line(_chunks(gzip_csv([HEADER, ROW, ROW]), 1)) == HEADER


def test_first_line_strips_a_byte_order_mark_and_carriage_return() -> None:
    data = gzip.compress(("﻿" + HEADER + "\r\n" + ROW + "\r\n").encode("utf-8"), mtime=0)
    assert first_line([data]) == HEADER


def test_first_line_of_a_file_with_no_newline_is_the_whole_file() -> None:
    assert first_line(_chunks(gzip.compress(HEADER.encode("utf-8"), mtime=0), 7)) == HEADER


def test_first_line_rejects_bytes_that_are_not_gzip() -> None:
    with pytest.raises(SourceError, match="gzip"):
        first_line([b"expansion,event_type\n"])


def test_card_names_come_from_the_deck_family_once_each_with_quoted_commas() -> None:
    assert parse_card_names(HEADER) == ("Plains", "Abigale, Poet Laureate", "Archaeomancer")


def test_fetch_reads_the_header_and_stops_without_downloading_the_file(
    clock: FakeClock,
) -> None:
    # Incompressible rows make the file far bigger than its header, like the real 4 MB file.
    rows = [f"SOS,Sealed,{random.Random(i).getrandbits(512):x},True" for i in range(2000)]
    body = ChunkedBody(gzip_csv([HEADER, *rows]), size=256)
    ctx = make_context(lambda request: httpx.Response(200, stream=body), clock)
    names = fetch_card_names(ctx, public_file_url("SOS", EventType.SEALED))
    assert names == ("Plains", "Abigale, Poet Laureate", "Archaeomancer")
    total_chunks = -(-len(body.data) // body.size)
    assert body.chunks_served <= 2 < total_chunks


def test_fetch_is_not_fooled_by_a_content_encoding_header(clock: FakeClock) -> None:
    body = ChunkedBody(gzip_csv([HEADER, ROW]))
    response = httpx.Response(200, stream=body, headers={"Content-Encoding": "gzip"})
    ctx = make_context(lambda request: response, clock)
    assert fetch_card_names(ctx, "https://example.test/x.csv.gz") == (
        "Plains",
        "Abigale, Poet Laureate",
        "Archaeomancer",
    )


@pytest.mark.parametrize("status", [403, 404])
def test_a_file_that_does_not_exist_yet_is_none(clock: FakeClock, status: int) -> None:
    ctx = make_context(lambda request: httpx.Response(status), clock)
    assert fetch_card_names(ctx, public_file_url("FRA", EventType.SEALED)) is None


def test_any_other_status_raises(clock: FakeClock) -> None:
    ctx = make_context(lambda request: httpx.Response(500), clock)
    with pytest.raises(SourceError, match="500"):
        fetch_card_names(ctx, public_file_url("SOS", EventType.SEALED))


def test_requests_to_17lands_are_spaced_a_second_apart(clock: FakeClock) -> None:
    ctx = make_context(lambda request: httpx.Response(404), clock)
    fetch_card_names(ctx, public_file_url("FRA", EventType.SEALED))
    fetch_card_names(ctx, public_file_url("FRA", EventType.PREMIER_DRAFT))
    assert clock.sleeps == [pytest.approx(1.0)]
