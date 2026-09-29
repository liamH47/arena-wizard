"""One HTTP client for every external source, with spacing, timeouts, and 429 back-off.

Every fetch in `sources/` takes a `SourceContext` instead of reaching for a module-level
client, so tests inject an `httpx.MockTransport`, a recording `sleep`, and a fake clock,
and no test ever touches the network or waits in real time.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

import httpx

from arena_wizard import __version__

USER_AGENT = f"arena-wizard/{__version__} (+https://github.com/liamH47/arena-wizard)"

TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)
"""A stalled download must fail, not hold a worker forever."""

DEFAULT_INTERVALS: Mapping[str, float] = {
    # Scryfall allows 2 requests per second on /cards/search and /cards/named, 10 on some
    # other endpoints (https://scryfall.com/docs/api/rate-limits, checked 2026-09-28). One
    # shared key at the stricter rate covers every endpoint this app calls, so interleaved
    # searches and named lookups can never outrun either limit.
    "scryfall": 0.5,
    "17lands": 1.0,
}

RATE_LIMITED_DELAY_SECONDS = 30.0
"""Scryfall locks access for 30 seconds after a 429, so no back-off is ever shorter."""


class SourceError(RuntimeError):
    """An external source failed in a way the caller cannot recover from by itself."""


@dataclass(slots=True)
class Throttle:
    """Keeps a minimum interval between requests that share a key.

    Mutable by design: it remembers when each key was last used.
    """

    intervals: Mapping[str, float]
    last_request: dict[str, float] = field(default_factory=dict)

    def wait(self, key: str, sleep: Callable[[float], None], now: Callable[[], float]) -> None:
        """Sleep until `key`'s interval has passed since its previous request, then stamp it.

        Args:
            key: Which interval applies, e.g. "scryfall".
            sleep: Sleeps for the given number of seconds.
            now: Returns a monotonic time in seconds.

        Raises:
            KeyError: `key` has no configured interval.
        """
        interval = self.intervals[key]
        previous = self.last_request.get(key)
        if previous is not None:
            remaining = interval - (now() - previous)
            if remaining > 0:
                sleep(remaining)
        self.last_request[key] = now()


@dataclass(frozen=True, slots=True)
class SourceContext:
    """Everything a fetch needs from the outside world, injected so tests control it."""

    client: httpx.Client
    sleep: Callable[[float], None]
    monotonic: Callable[[], float]
    throttle: Throttle


def build_client(transport: httpx.BaseTransport | None = None) -> httpx.Client:
    """Build the shared client with the identifying headers every source requires.

    Args:
        transport: A transport to use instead of the network, for tests.

    Returns:
        A client that sends User-Agent and Accept headers and enforces timeouts.
    """
    return httpx.Client(
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        timeout=TIMEOUT,
        transport=transport,
    )


def default_context(transport: httpx.BaseTransport | None = None) -> SourceContext:
    """Build a context backed by the real clock and the given (or real) transport."""
    return SourceContext(
        client=build_client(transport),
        sleep=time.sleep,
        monotonic=time.monotonic,
        throttle=Throttle(DEFAULT_INTERVALS),
    )


def retry_after_seconds(response: httpx.Response) -> float:
    """Return how long to wait after a 429: the server's Retry-After, never under 30 seconds.

    Args:
        response: A 429 response.

    Returns:
        The delay to wait before retrying.
    """
    try:
        seconds = float(response.headers.get("Retry-After", ""))
    except ValueError:
        return RATE_LIMITED_DELAY_SECONDS
    return max(seconds, RATE_LIMITED_DELAY_SECONDS)


def get(
    ctx: SourceContext,
    url: str,
    *,
    key: str,
    params: Mapping[str, str] | None = None,
    max_attempts: int = 3,
) -> httpx.Response:
    """GET a URL with spacing and 429 back-off. Other statuses are returned to the caller.

    Args:
        ctx: The injected context.
        url: The URL to fetch.
        key: The throttle key that sets the spacing.
        params: Query parameters.
        max_attempts: Total attempts before a run of 429s becomes an error.

    Returns:
        The first response that is not a 429.

    Raises:
        SourceError: Every attempt was rate limited.
    """
    for _ in range(max_attempts):
        ctx.throttle.wait(key, ctx.sleep, ctx.monotonic)
        response = ctx.client.get(url, params=params)
        if response.status_code != 429:
            return response
        ctx.sleep(retry_after_seconds(response))
    raise SourceError(f"rate limited on every one of {max_attempts} attempts: {url}")
