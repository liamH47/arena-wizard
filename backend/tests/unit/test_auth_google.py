from __future__ import annotations

import base64
import json
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from arena_wizard.auth.google import (
    AUTHORIZE_URL,
    TOKEN_URL,
    ExchangeError,
    authorize_url,
    exchange_code,
    jwt_claims,
    validate_claims,
)
from arena_wizard.auth.session import SessionUser

CLIENT = "client-id.apps.example.com"
NOW = 1_800_000_000.0
GOOD: dict[str, Any] = {
    "aud": CLIENT,
    "iss": "https://accounts.google.com",
    "exp": NOW + 3600,
    "email_verified": True,
    "sub": "sub-1",
    "email": "Friend@Example.com",
    "name": "Friend",
    "picture": "https://example.com/p.png",
}


def _jwt(claims: object) -> str:
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    return f"header.{payload}.signature"


def test_the_authorize_url_asks_google_for_an_openid_code() -> None:
    url = urlparse(authorize_url(CLIENT, "https://w.example.com/auth/google/callback", "st"))
    assert f"{url.scheme}://{url.netloc}{url.path}" == AUTHORIZE_URL
    query = {k: v[0] for k, v in parse_qs(url.query).items()}
    assert query == {
        "client_id": CLIENT,
        "redirect_uri": "https://w.example.com/auth/google/callback",
        "response_type": "code",
        "scope": "openid email profile",
        "state": "st",
    }


def test_jwt_claims_decodes_the_payload_without_padding() -> None:
    assert jwt_claims(_jwt(GOOD)) == GOOD


@pytest.mark.parametrize(
    ("token", "message"),
    [
        ("only.two", "not a JWT"),
        ("a.b.c.d", "not a JWT"),
        ("header.!!!notbase64json.sig", "would not decode"),
        (_jwt(["a", "list"]), "not a claims object"),
    ],
)
def test_malformed_id_tokens_are_refused(token: str, message: str) -> None:
    with pytest.raises(ExchangeError, match=message):
        jwt_claims(token)


def test_valid_claims_name_the_user_with_a_lower_cased_email() -> None:
    assert validate_claims(GOOD, client_id=CLIENT, now=NOW) == SessionUser(
        "sub-1", "friend@example.com", "Friend", "https://example.com/p.png"
    )


def test_the_short_issuer_form_and_missing_profile_fields_are_accepted() -> None:
    claims = dict(GOOD, iss="accounts.google.com")
    del claims["name"], claims["picture"]
    assert validate_claims(claims, client_id=CLIENT, now=NOW) == SessionUser(
        "sub-1", "friend@example.com", "", ""
    )


@pytest.mark.parametrize(
    ("change", "claim"),
    [
        ({"aud": "another-client"}, "aud"),
        ({"iss": "https://evil.example.com"}, "iss"),
        ({"exp": None}, "exp"),
        ({"exp": True}, "exp"),
        ({"exp": "later"}, "exp"),
        ({"exp": NOW}, "exp"),
        ({"exp": NOW - 1}, "exp"),
        ({"email_verified": False}, "email_verified"),
        ({"email_verified": None}, "email_verified"),
        ({"email_verified": "true"}, "email_verified"),
        ({"sub": ""}, "sub, email"),
        ({"email": None}, "sub, email"),
    ],
)
def test_each_failing_claim_is_refused_by_name(change: dict[str, Any], claim: str) -> None:
    claims = {k: v for k, v in (GOOD | change).items() if v is not None}
    with pytest.raises(ExchangeError, match=f"\\({claim}\\)"):
        validate_claims(claims, client_id=CLIENT, now=NOW)


def _exchange(response: httpx.Response) -> SessionUser:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == TOKEN_URL
        form = parse_qs(request.content.decode())
        assert form["code"] == ["the-code"] and form["grant_type"] == ["authorization_code"]
        return response

    return exchange_code(
        "the-code",
        client_id=CLIENT,
        client_secret="secret",
        redirect_uri="https://w.example.com/auth/google/callback",
        now=NOW,
        transport=httpx.MockTransport(handler),
    )


def test_a_successful_exchange_returns_the_validated_user() -> None:
    user = _exchange(httpx.Response(200, json={"id_token": _jwt(GOOD)}))
    assert user.email == "friend@example.com" and user.user_id == "sub-1"


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (httpx.Response(400, json={"error": "invalid_grant"}), "HTTP 400"),
        (httpx.Response(200, content=b"<html>"), "not JSON"),
        (httpx.Response(200, json={"access_token": "x"}), "no id_token"),
        (httpx.Response(200, json=["not", "an", "object"]), "no id_token"),
    ],
)
def test_a_failed_exchange_raises_with_the_reason(response: httpx.Response, message: str) -> None:
    with pytest.raises(ExchangeError, match=message):
        _exchange(response)


def test_an_exchanged_token_with_bad_claims_is_refused() -> None:
    with pytest.raises(ExchangeError, match="aud"):
        _exchange(httpx.Response(200, json={"id_token": _jwt(dict(GOOD, aud="other"))}))


def test_not_reaching_google_is_an_exchange_error() -> None:
    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host", request=request)

    with pytest.raises(ExchangeError, match=r"could not reach Google \(ConnectError\)"):
        exchange_code(
            "code",
            client_id="cid",
            client_secret="secret",
            redirect_uri="https://aw.example.com/auth/google/callback",
            now=0.0,
            transport=httpx.MockTransport(unreachable),
        )
