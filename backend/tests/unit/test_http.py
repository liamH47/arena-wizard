from __future__ import annotations

from itertools import pairwise

import httpx
import pytest

from arena_wizard.sources.http import (
    DEFAULT_INTERVALS,
    RATE_LIMITED_DELAY_SECONDS,
    USER_AGENT,
    SourceError,
    Throttle,
    default_context,
    get,
    retry_after_seconds,
)
from tests.conftest import FakeClock, Handler, make_context


def _recording_handler(
    clock: FakeClock, sent_at: list[float], responses: list[httpx.Response] | None = None
) -> Handler:
    """A handler that stamps each request with the fake clock's time when it is sent."""
    queue = list(responses or [])

    def handler(request: httpx.Request) -> httpx.Response:
        sent_at.append(clock.now())
        return queue.pop(0) if queue else httpx.Response(200)

    return handler


def test_requests_on_one_key_are_sent_at_least_an_interval_apart(clock: FakeClock) -> None:
    sent_at: list[float] = []
    ctx = make_context(_recording_handler(clock, sent_at), clock)
    for elapsed in (0.0, 0.2, 0.1, 0.7, 0.0):
        clock.time += elapsed  # time the caller spends between requests
        get(ctx, "https://api.scryfall.com/x", key="scryfall")
    assert len(sent_at) == 5
    assert all(later - earlier >= 0.5 for earlier, later in pairwise(sent_at))


def test_a_request_after_the_interval_has_passed_does_not_wait(clock: FakeClock) -> None:
    throttle = Throttle({"17lands": 1.0})
    throttle.wait("17lands", clock.sleep, clock.now)
    clock.time += 5.0
    throttle.wait("17lands", clock.sleep, clock.now)
    assert clock.sleeps == []


def test_keys_are_spaced_independently(clock: FakeClock) -> None:
    throttle = Throttle({"a": 1.0, "b": 1.0})
    throttle.wait("a", clock.sleep, clock.now)
    throttle.wait("b", clock.sleep, clock.now)
    assert clock.sleeps == []


def test_every_scryfall_endpoint_shares_the_two_per_second_limit() -> None:
    assert DEFAULT_INTERVALS["scryfall"] == 0.5


def test_an_unconfigured_key_is_an_error_not_an_unthrottled_request(clock: FakeClock) -> None:
    with pytest.raises(KeyError):
        Throttle({}).wait("unknown", clock.sleep, clock.now)


def test_every_request_identifies_itself_and_asks_for_json(clock: FakeClock) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={})

    get(make_context(handler, clock), "https://api.scryfall.com/x", key="scryfall")
    assert seen[0].headers["User-Agent"] == USER_AGENT
    assert seen[0].headers["Accept"] == "application/json"


def test_non_429_statuses_are_returned_for_the_caller_to_judge(clock: FakeClock) -> None:
    ctx = make_context(lambda request: httpx.Response(404), clock)
    assert get(ctx, "https://api.scryfall.com/x", key="scryfall").status_code == 404


def test_every_retry_after_a_429_waits_out_the_lockout_first(clock: FakeClock) -> None:
    sent_at: list[float] = []
    responses = [
        httpx.Response(429, headers={"Retry-After": "45"}),
        httpx.Response(429),
        httpx.Response(200),
    ]
    ctx = make_context(_recording_handler(clock, sent_at, responses), clock)
    assert get(ctx, "https://api.scryfall.com/x", key="scryfall").status_code == 200
    gaps = [later - earlier for earlier, later in pairwise(sent_at)]
    assert gaps[0] >= 45.0
    assert gaps[1] >= RATE_LIMITED_DELAY_SECONDS


def test_rate_limited_on_every_attempt_raises_instead_of_looping(clock: FakeClock) -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(429)

    with pytest.raises(SourceError, match="3 attempts"):
        get(make_context(handler, clock), "https://api.scryfall.com/x", key="scryfall")
    assert len(calls) == 3


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ({"Retry-After": "45"}, 45.0),
        ({"Retry-After": "1"}, RATE_LIMITED_DELAY_SECONDS),
        ({}, RATE_LIMITED_DELAY_SECONDS),
        ({"Retry-After": "soon"}, RATE_LIMITED_DELAY_SECONDS),
        ({"Retry-After": "-5"}, RATE_LIMITED_DELAY_SECONDS),
    ],
)
def test_a_429_never_waits_less_than_the_thirty_second_lockout(
    header: dict[str, str], expected: float
) -> None:
    assert retry_after_seconds(httpx.Response(429, headers=header)) == expected


def test_the_default_context_uses_the_given_transport() -> None:
    ctx = default_context(httpx.MockTransport(lambda request: httpx.Response(204)))
    assert ctx.client.get("https://example.test/").status_code == 204
