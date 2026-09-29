"""The container's entrypoint: wait for the database, migrate, then serve.

Neon's compute sleeps when idle and takes seconds to wake, and Render starts the app as
soon as the instance does, so the first connection can fail. Connection failures are
retried with back-off for up to 90 seconds, one log line per attempt; a failing migration
is fatal at once, because retrying bad SQL only hides it (docs/plan.md section 11).
"""

from __future__ import annotations

import os
import sys
import time
from collections.abc import Callable
from importlib import resources

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.exc import OperationalError

from arena_wizard.config import Settings
from arena_wizard.db.session import make_engine
from arena_wizard.main import serve

DEADLINE_SECONDS = 90.0
MAX_DELAY_SECONDS = 10.0


class DatabaseUnavailable(RuntimeError):
    """The database did not answer before the deadline."""


def wait_for_database(
    connect: Callable[[], None],
    sleep: Callable[[float], None],
    monotonic: Callable[[], float],
    log: Callable[[str], None],
    deadline: float = DEADLINE_SECONDS,
) -> int:
    """Try to connect until it works or the deadline passes.

    Returns:
        How many attempts it took.

    Raises:
        DatabaseUnavailable: Still failing at the deadline; the last error is chained.
    """
    start = monotonic()
    delay = 1.0
    attempt = 0
    while True:
        attempt += 1
        try:
            connect()
        except OperationalError as error:
            elapsed = monotonic() - start
            log(f"database not ready (attempt {attempt}, {elapsed:.0f}s): {error.orig}")
            if elapsed + delay > deadline:
                raise DatabaseUnavailable(
                    f"no database after {attempt} attempts in {elapsed:.0f}s"
                ) from error
            sleep(delay)
            delay = min(delay * 2, MAX_DELAY_SECONDS)
        else:
            log(f"database ready after {attempt} attempt(s)")
            return attempt


def alembic_config(url: str) -> Config:
    """Alembic settings pointing at the migrations shipped inside the package."""
    config = Config()
    location = resources.files("arena_wizard").joinpath("db", "migrations")
    config.set_main_option("script_location", str(location))
    # Alembic's config interpolates %; a percent-encoded password must survive it.
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return config


def database_revision(url: str) -> str | None:
    """The revision the database is at, or None before the first migration."""
    engine = make_engine(url)
    try:
        with engine.connect() as connection:
            return MigrationContext.configure(connection).get_current_revision()
    finally:
        engine.dispose()


def migrate(url: str, log: Callable[[str], None] = print) -> None:
    """Bring the database to this build's newest schema.

    A database already at a revision this build does not know is newer than the build:
    a rollback. The old build serves without migrating, because every migration leaves the
    previous release working (decision 0008); refusing would leave the broken deploy live.
    """
    config = alembic_config(url)
    scripts = ScriptDirectory.from_config(config)
    head = scripts.get_current_head()
    current = database_revision(url)
    if current is not None and current not in {s.revision for s in scripts.walk_revisions()}:
        log(
            f"database at revision {current}, ahead of this build's head {head}; serving "
            "without migrating (a rollback)"
        )
        return
    log(f"migrating from {current or 'an empty database'} to {head}")
    command.upgrade(config, "head")


def main() -> None:
    """Wait, migrate, serve. Orchestration only; each step above is tested."""
    settings = Settings()
    engine = make_engine(settings.database_url)

    def connect() -> None:
        engine.connect().close()

    try:
        wait_for_database(connect, time.sleep, time.monotonic, print)
    except DatabaseUnavailable as error:
        print(f"giving up: {error}")
        sys.exit(1)
    migrate(settings.database_url)
    serve(int(os.environ.get("PORT", "8000")))


if __name__ == "__main__":
    main()
