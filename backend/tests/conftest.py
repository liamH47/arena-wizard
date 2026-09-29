from __future__ import annotations

import gzip
import json
import socket
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from arena_wizard.sources.http import DEFAULT_INTERVALS, SourceContext, Throttle, build_client

FIXTURES = Path(__file__).parent / "fixtures"
LOOPBACK = ("127.0.0.1", "::1", "localhost")
"""Local socket pairs (asyncio on Windows) may connect; nothing else may."""


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


@pytest.fixture(autouse=True)
def _isolated(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep every test away from the owner's real data, cache, and network (decision 0007).

    Private pastes live under the data directory; a test that forgot to pass one would
    otherwise read or overwrite real pasted data. Sockets are blocked so that only an
    injected `httpx.MockTransport` can answer a request.
    """
    home = tmp_path_factory.mktemp("home")
    for name in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(name, str(home))
    monkeypatch.setenv("ARENA_WIZARD_DATA_DIR", str(tmp_path_factory.mktemp("data")))
    monkeypatch.setenv("ARENA_WIZARD_CACHE_DIR", str(tmp_path_factory.mktemp("cache")))

    real_connect = socket.socket.connect

    def local_only(sock: socket.socket, address: Any) -> None:
        host = address[0] if isinstance(address, tuple) else address
        if host not in LOOPBACK:
            raise OSError(f"tests may not open network connections (tried {host!r})")
        real_connect(sock, address)

    monkeypatch.setattr(socket.socket, "connect", local_only)


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
