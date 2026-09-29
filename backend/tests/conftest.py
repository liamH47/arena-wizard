from __future__ import annotations

import gzip
import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from arena_wizard.sources.http import DEFAULT_INTERVALS, SourceContext, Throttle, build_client

FIXTURES = Path(__file__).parent / "fixtures"


class FakeClock:
    """A monotonic clock that only moves when something sleeps, and records every sleep."""

    def __init__(self) -> None:
        self.time = 1000.0
        self.sleeps: list[float] = []

    def now(self) -> float:
        return self.time

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.time += seconds


Handler = Callable[[httpx.Request], httpx.Response]


def make_context(handler: Handler, clock: FakeClock) -> SourceContext:
    return SourceContext(
        client=build_client(httpx.MockTransport(handler)),
        sleep=clock.sleep,
        monotonic=clock.now,
        throttle=Throttle(DEFAULT_INTERVALS),
    )


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def scryfall_cards() -> dict[str, dict[str, Any]]:
    """Real Scryfall card objects captured 2026-09-28, one per layout the code handles."""
    data: dict[str, dict[str, Any]] = json.loads(
        (FIXTURES / "scryfall" / "cards.json").read_text(encoding="utf-8")
    )
    return data


class ChunkedBody(httpx.SyncByteStream):
    """A streamed response body, like a real download, that counts the chunks it served."""

    def __init__(self, data: bytes, size: int = 64) -> None:
        self.data = data
        self.size = size
        self.chunks_served = 0

    def __iter__(self) -> Iterator[bytes]:
        for start in range(0, len(self.data), self.size):
            self.chunks_served += 1
            yield self.data[start : start + self.size]


def gzip_csv(lines: list[str]) -> bytes:
    """Gzip CSV lines the way 17Lands publishes them: UTF-8, LF endings."""
    return gzip.compress(("\n".join(lines) + "\n").encode("utf-8"), mtime=0)
