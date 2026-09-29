"""The real app on a migrated database, for API tests. Never reads the environment.

The database is a fresh SQLite file, or the shared Postgres when `AW_TEST_DB_URL` is set
(see `tests/database.py`), always built by the migrations.

- `make_app` is the sign-in harness: one listed friend, the app, a client on
  https://testserver (so Secure cookies are kept), and the session factory.
- `make` is the data harness: Alice (the owner) and Bob as users, a settable clock, and
  `as_user` headers.
"""

from __future__ import annotations

import datetime as dt
import random
import uuid
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from arena_wizard.auth.session import COOKIE_NAME, SessionUser, sign_session
from arena_wizard.catalog import load_packaged_card_table
from arena_wizard.config import Settings
from arena_wizard.db import repository
from arena_wizard.db.session import session_factory
from arena_wizard.main import MAX_BODY_BYTES, create_app, ensure_local_user
from tests.database import fresh_database, tracked_engine
from tests.unit.test_paste_commands import grades_csv

FIXED = dt.datetime(2026, 10, 3, 18, 0, tzinfo=dt.UTC)
NOON = dt.datetime(2026, 10, 3, 12, 0, tzinfo=dt.UTC)
SECRET = "test-secret-key-long-enough-to-sign"
CLIENT_ID = "client-id.apps.example.com"
PUBLIC_URL = "https://testserver"
FRIEND = SessionUser(user_id="sub-friend", email="friend@example.com", name="Friend")
ALICE = SessionUser("sub-alice", "alice@example.com", "Alice")
BOB = SessionUser("sub-bob", "bob@example.com", "Bob")

App = tuple[FastAPI, TestClient, sessionmaker[Session]]


def make_settings(
    auth: str = "off", allowed: Sequence[str] = ("friend@example.com",), **extra: Any
) -> Settings:
    """Settings built explicitly, never from the environment or a .env file."""
    values: dict[str, Any] = {"auth": auth, "database_url": "sqlite://"}
    if auth == "google":
        values |= {
            "google_client_id": CLIENT_ID,
            "google_client_secret": "client-secret",
            "secret_key": SECRET,
            "public_url": PUBLIC_URL,
            "allowed_emails": list(allowed),
            "owner_email": "owner@example.com",
        }
    return Settings(_env_file=None, **(values | extra))  # type: ignore[call-arg]


def make_app(
    tmp_path: Path,
    *,
    auth: str = "off",
    allowed: Sequence[str] = ("friend@example.com",),
    exchanger: Callable[[str, float], SessionUser] | None = None,
    now: dt.datetime = FIXED,
    **extra: Any,
) -> App:
    """A migrated database, the app on it, and a client, for sign-in tests."""
    sessions = session_factory(tracked_engine(fresh_database(tmp_path)))
    settings = make_settings(auth, allowed, **extra)
    if auth == "off":
        ensure_local_user(sessions, now)
    app = create_app(settings, sessions=sessions, token_exchanger=exchanger, now=lambda: now)
    return app, TestClient(app, base_url="https://testserver"), sessions


def signed_in(client: TestClient, settings: Settings, user: SessionUser = FRIEND) -> None:
    """Give the client the session cookie the Google callback would have set."""
    client.cookies.set(COOKIE_NAME, sign_session(settings.secret_key or "", user))


class Clock:
    """A settable clock for the app."""

    def __init__(self, now: dt.datetime = NOON) -> None:
        self.value = now

    def __call__(self) -> dt.datetime:
        return self.value


def make(
    tmp_path: Path,
    *,
    auth: str = "google",
    static_dir: Path | None = None,
    clock: Clock | None = None,
    max_body_bytes: int = MAX_BODY_BYTES,
    url: str | None = None,
) -> App:
    """The real app on a fresh migrated database, with Alice (the owner) and Bob as users.

    `url` names a database already prepared by the caller (the Postgres tests); otherwise
    the shared seam picks one.
    """
    database = url or fresh_database(tmp_path)
    sessions = session_factory(tracked_engine(database))
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        auth=auth,  # type: ignore[arg-type]
        google_client_id="client-id",
        google_client_secret="client-secret",
        secret_key=SECRET,
        public_url="https://aw.example.com",
        allowed_emails=[ALICE.email, BOB.email],
        owner_email=ALICE.email,
        database_url=database,
        static_dir=static_dir,
    )
    with sessions() as session:
        for user in (ALICE, BOB):
            repository.upsert_user(session, user.user_id, user.email, user.name, "", NOON)
    ensure_local_user(sessions, NOON)
    app = create_app(
        settings, sessions=sessions, now=clock or Clock(), max_body_bytes=max_body_bytes
    )
    return app, TestClient(app, base_url="https://testserver"), sessions


def as_user(user: SessionUser) -> dict[str, str]:
    """Headers carrying a signed session cookie for the user."""
    return {"cookie": f"{COOKIE_NAME}={sign_session(SECRET, user)}"}


def fra_pool(seed: int = 3, size: int = 83) -> str:
    """A made-up FRA pool as Arena export lines."""
    cards = [c for c in load_packaged_card_table("FRA").cards if not c.is_basic]
    picks = random.Random(seed).sample(cards, size)
    return "\n".join(f"1 {c.name} ({c.set_code.upper()}) {c.collector_number}" for c in picks)


def create(
    client: TestClient,
    user: SessionUser = ALICE,
    *,
    pool_id: str | None = None,
    text: str | None = None,
    set_code: str = "FRA",
    fmt: str = "bo1_sealed",
) -> Any:
    """POST a pool and return the response."""
    body = {
        "id": pool_id or str(uuid.uuid4()),
        "set_code": set_code,
        "format": fmt,
        "export_text": text if text is not None else fra_pool(),
    }
    return client.post("/api/pools", json=body, headers=as_user(user))


def paste_grades(client: TestClient, user: SessionUser = ALICE, seed: int = 1) -> Any:
    """Paste a made-up full-set grade list for FRA."""
    body = {
        "set_code": "FRA",
        "dataset": "grades",
        "source_id": "llu-marc",
        "text": grades_csv(seed=seed).decode("utf-8"),
    }
    return client.post("/api/pastes", json=body, headers=as_user(user))
