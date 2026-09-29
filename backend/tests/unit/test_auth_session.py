from __future__ import annotations

import base64
import json

from arena_wizard.auth.session import (
    MAX_AGE_SECONDS,
    SessionUser,
    _sig,
    sign_session,
    verify_session,
)

SECRET = "a-long-random-secret"
USER = SessionUser("sub-1", "friend@example.com", "Friend", "https://example.com/p.png")
NOW = 1_800_000_000.0


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _forged(claims: object) -> str:
    """A token we signed ourselves around an arbitrary payload."""
    payload = _b64(json.dumps(claims).encode()) if not isinstance(claims, bytes) else _b64(claims)
    return f"{payload}.{_sig(SECRET, payload)}"


def test_a_signed_session_verifies_back_to_the_same_user() -> None:
    token = sign_session(SECRET, USER, now=NOW)
    assert verify_session(SECRET, token, now=NOW + 60) == USER


def test_the_real_clock_is_used_when_none_is_given() -> None:
    assert verify_session(SECRET, sign_session(SECRET, USER)) == USER


def test_a_session_expires_after_its_maximum_age() -> None:
    token = sign_session(SECRET, USER, now=NOW)
    assert verify_session(SECRET, token, now=NOW + MAX_AGE_SECONDS - 1) == USER
    assert verify_session(SECRET, token, now=NOW + MAX_AGE_SECONDS) is None


def test_another_secret_or_a_tampered_payload_fails() -> None:
    token = sign_session(SECRET, USER, now=NOW)
    assert verify_session("other-secret", token, now=NOW) is None
    payload, signature = token.split(".")
    tampered = _b64(json.dumps({"sub": "someone-else", "exp": NOW + 999}).encode())
    assert verify_session(SECRET, f"{tampered}.{signature}", now=NOW) is None


def test_a_truncated_or_malformed_token_fails() -> None:
    token = sign_session(SECRET, USER, now=NOW)
    assert verify_session(SECRET, token.split(".")[0], now=NOW) is None
    assert verify_session(SECRET, token + ".extra", now=NOW) is None
    assert verify_session(SECRET, "", now=NOW) is None


def test_a_signed_payload_that_is_not_json_reads_as_signed_out() -> None:
    assert verify_session(SECRET, _forged(b"not json"), now=NOW) is None


def test_signed_claims_without_a_valid_expiry_or_subject_fail() -> None:
    assert verify_session(SECRET, _forged(["a", "list"]), now=NOW) is None
    assert verify_session(SECRET, _forged({"sub": "x"}), now=NOW) is None
    assert verify_session(SECRET, _forged({"sub": "x", "exp": "soon"}), now=NOW) is None
    assert verify_session(SECRET, _forged({"sub": "", "exp": NOW + 10}), now=NOW) is None


def test_missing_optional_claims_default_to_empty_strings() -> None:
    user = verify_session(SECRET, _forged({"sub": "x", "exp": NOW + 10}), now=NOW)
    assert user == SessionUser("x", "", "", "")
