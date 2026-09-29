from __future__ import annotations

import httpx
import pytest

from arena_wizard.sources.http import (
    RATE_LIMITED_DELAY_SECONDS,
    USER_AGENT,
    SourceError,
    Throttle,
    default_context,
    get,
    retry_after_seconds,
)
from tests.conftest import FakeClock, make_context


def test_first_request_on_a_key_does_not_wait(clock: FakeClock) -> None:
    Throttle({"scryfall": 0.1}).wait("scryfall", clock.sleep, clock.now)
    assert clock.sleeps == []


def test_back_to_back_requests_wait_out_the_remaining_interval(clock: FakeClock) -> None:
    throttle = Throttle({"scryfall_search": 0.5})
    throttle.wait("scryfall_search", clock.sleep, clock.now)
    clock.time += 0.2
    throttle.wait("scryfall_search", clock.sleep, clock.now)
    assert clock.sleeps == [pytest.approx(0.3)]


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


def test_a_429_waits_for_retry_after_then_succeeds(clock: FakeClock) -> None:
    responses = iter([httpx.Response(429, headers={"Retry-After": "7"}), httpx.Response(200)])
    ctx = make_context(lambda request: next(responses), clock)
    assert get(ctx, "https://api.scryfall.com/x", key="scryfall").status_code == 200
    assert 7.0 in clock.sleeps


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
        ({"Retry-After": "12"}, 12.0),
        ({}, RATE_LIMITED_DELAY_SECONDS),
        ({"Retry-After": "soon"}, RATE_LIMITED_DELAY_SECONDS),
        ({"Retry-After": "-5"}, RATE_LIMITED_DELAY_SECONDS),
    ],
)
def test_retry_after_falls_back_to_thirty_seconds_when_absent_or_invalid(
    header: dict[str, str], expected: float
) -> None:
    assert retry_after_seconds(httpx.Response(429, headers=header)) == expected


def test_the_default_context_uses_the_given_transport() -> None:
    ctx = default_context(httpx.MockTransport(lambda request: httpx.Response(204)))
    assert ctx.client.get("https://example.test/").status_code == 204
