"""Engines and sessions for SQLite (tests, local) and Postgres (production, via Neon).

Error messages never carry bound parameters: a failed paste insert would otherwise put
pasted rows into the logs, which decision 0005 forbids. In production connections are
checked before use and recycled every five minutes, because Neon closes idle ones; Neon
documents that idle connections do not keep its compute awake. Server-side prepared
statements are off, so the pooler's transaction mode can never lose one. Connecting gives
up after ten seconds instead of hanging a request (docs/plan.md section 11, decision 0008).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event, make_url
from sqlalchemy.orm import Session, sessionmaker


def _sqlite_foreign_keys(dbapi_connection: Any, _: Any) -> None:
    """SQLite ignores foreign keys unless each connection turns them on."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def make_engine(url: str) -> Engine:
    """An engine for the URL: foreign keys on for SQLite, Neon-safe settings for Postgres."""
    if url.startswith("sqlite"):
        database = make_url(url).database
        if database and database != ":memory:":
            # SQLite creates the file but not its directory; a fresh data directory would
            # otherwise fail every connection and the entrypoint would wait forever.
            Path(database).parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(url, connect_args={"check_same_thread": False}, hide_parameters=True)
        event.listen(engine, "connect", _sqlite_foreign_keys)
        return engine
    return create_engine(
        url,
        pool_pre_ping=True,
        pool_recycle=300,
        hide_parameters=True,
        connect_args={"connect_timeout": 10, "prepare_threshold": None},
    )


def session_factory(engine: Engine) -> sessionmaker[Session]:
    """Sessions that keep loaded rows usable after commit, for building responses."""
    return sessionmaker(engine, expire_on_commit=False)


MIGRATION_LOCK = 72_051_901
"""A transaction-scoped advisory lock, so two instances booting at once migrate in turn.
Transaction-scoped because a session lock does not survive Neon's transaction pooler."""


def migration_lock_sql(dialect: str) -> str:
    """The statement that serializes migrations: an advisory lock on Postgres, a no-op
    elsewhere (SQLite has one writer anyway)."""
    if dialect == "postgresql":
        return f"SELECT pg_advisory_xact_lock({MIGRATION_LOCK})"
    return "SELECT 1"
