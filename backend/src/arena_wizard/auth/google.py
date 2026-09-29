"""The Google OAuth code exchange. Ported from draft-kit, with claim validation added.

The HTTP call takes an injectable transport; parsing and validation are pure functions.
The id_token's signature is not checked against Google's keys: this is a confidential
client, so the token arrives straight from Google's token endpoint over TLS. Its claims
are still checked, because a token for another client, an expired one, or an unverified
email must never sign anyone in (docs/plan.md section 10).
"""

from __future__ import annotations

import base64
import json
from typing import Any
from urllib.parse import urlencode

import httpx

from arena_wizard.auth.session import SessionUser

AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
ISSUERS = ("https://accounts.google.com", "accounts.google.com")


class ExchangeError(Exception):
    """The sign-in could not be completed; the message names the reason."""


def authorize_url(client_id: str, redirect_uri: str, state: str) -> str:
    """Where to send the browser to start signing in."""
    query = urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
        }
    )
    return f"{AUTHORIZE_URL}?{query}"


def jwt_claims(id_token: str) -> dict[str, Any]:
    """The claims inside an id_token, decoded without verifying its signature. Pure.

    Raises:
        ExchangeError: Not a three-part JWT, or its payload is not a JSON object.
    """
    parts = id_token.split(".")
    if len(parts) != 3:
        raise ExchangeError("Google's id_token is not a JWT")
    try:
        claims = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
    except ValueError as exc:
        raise ExchangeError("Google's id_token payload would not decode") from exc
    if not isinstance(claims, dict):
        raise ExchangeError("Google's id_token payload is not a claims object")
    return claims


def validate_claims(claims: dict[str, Any], *, client_id: str, now: float) -> SessionUser:
    """Check an id_token's claims and return who it names. Pure.

    Raises:
        ExchangeError: Naming the first claim that fails: audience, issuer, expiry,
            verified email, or a missing subject or email.
    """
    if claims.get("aud") != client_id:
        raise ExchangeError("the id_token is for another client (aud)")
    if claims.get("iss") not in ISSUERS:
        raise ExchangeError("the id_token was not issued by Google (iss)")
    exp = claims.get("exp")
    if isinstance(exp, bool) or not isinstance(exp, int | float) or exp <= now:
        raise ExchangeError("the id_token has expired (exp)")
    if claims.get("email_verified") is not True:
        raise ExchangeError("Google has not verified this email address (email_verified)")
    sub, email = claims.get("sub"), claims.get("email")
    if not sub or not email:
        raise ExchangeError("the id_token names no subject or email (sub, email)")
    return SessionUser(
        user_id=str(sub),
        email=str(email).lower(),
        name=str(claims.get("name") or ""),
        picture=str(claims.get("picture") or ""),
    )


def exchange_code(
    code: str,
    *,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    now: float,
    transport: httpx.BaseTransport | None = None,
) -> SessionUser:
    """Trade an authorization code for a validated identity.

    Raises:
        ExchangeError: Google refused the code, answered with something unexpected, or
            the id_token's claims fail validation.
    """
    try:
        with httpx.Client(transport=transport, timeout=10.0) as client:
            resp = client.post(
                TOKEN_URL,
                data={
                    "code": code,
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                },
            )
    except httpx.HTTPError as exc:
        raise ExchangeError(f"could not reach Google ({type(exc).__name__})") from exc
    if resp.status_code != 200:
        raise ExchangeError(f"Google refused the code exchange (HTTP {resp.status_code})")
    try:
        body = resp.json()
    except ValueError as exc:
        raise ExchangeError("Google's token response was not JSON") from exc
    id_token = body.get("id_token") if isinstance(body, dict) else None
    if not id_token:
        raise ExchangeError("Google's token response held no id_token")
    return validate_claims(jwt_claims(str(id_token)), client_id=client_id, now=now)
