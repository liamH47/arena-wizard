"""Signed session cookies, stdlib only. Ported from draft-kit.

The token is b64url(json claims) + "." + b64url(hmac_sha256(secret, claims)).
Every way verification can fail — tampering, truncation, expiry, a payload we
never signed — collapses to None, because the caller's answer is the same 401
regardless of which it was.
"""

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass

COOKIE_NAME = "aw_session"
MAX_AGE_SECONDS = 30 * 24 * 3600
"""Thirty days: long enough to span an event, short enough that a lost cookie expires."""


@dataclass(frozen=True, slots=True)
class SessionUser:
    """Who a request is from: Google's subject id, or "local" when auth is off."""

    user_id: str
    email: str
    name: str = ""
    picture: str = ""


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sig(secret: str, payload: str) -> str:
    return _b64(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest())


def sign_session(secret: str, user: SessionUser, *, now: float | None = None) -> str:
    """A cookie value: base64url claims, a dot, and their HMAC-SHA256."""
    issued = time.time() if now is None else now
    claims = {
        "sub": user.user_id,
        "email": user.email,
        "name": user.name,
        "picture": user.picture,
        "exp": issued + MAX_AGE_SECONDS,
    }
    payload = _b64(json.dumps(claims).encode())
    return f"{payload}.{_sig(secret, payload)}"


def verify_session(secret: str, token: str, *, now: float | None = None) -> SessionUser | None:
    """The user a cookie names, or None for any tampered, expired, or malformed value."""
    parts = token.split(".")
    if len(parts) != 2:
        return None
    payload, signature = parts
    if not token.isascii():
        return None
    if not hmac.compare_digest(signature, _sig(secret, payload)):
        return None
    # Past the HMAC, the payload is one we signed — but decode defensively
    # anyway: a stale cookie from an older build should read as "signed out",
    # never as a 500.
    try:
        claims = json.loads(_unb64(payload))
    except ValueError:
        return None
    exp = claims.get("exp") if isinstance(claims, dict) else None
    if not isinstance(exp, int | float) or exp <= (time.time() if now is None else now):
        return None
    sub = claims.get("sub")
    if not sub:
        return None
    return SessionUser(
        user_id=str(sub),
        email=str(claims.get("email", "")),
        name=str(claims.get("name", "")),
        picture=str(claims.get("picture", "")),
    )
