"""Liveness and readiness, answerable without waking the database.

Render's health check and the keep-warm ping hit these every few minutes; if they opened a
database session, Neon's compute would never sleep and the free budget would drain
(docs/plan.md section 11). Only `/readyz?deep=1` touches the database.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from sqlalchemy import text

from arena_wizard import __version__

router = APIRouter()


@router.api_route("/healthz", methods=["GET", "HEAD"])
def healthz() -> dict[str, str]:
    """Liveness: no dependencies, so it cannot flap."""
    return {"status": "ok"}


@router.api_route("/readyz", methods=["GET", "HEAD"])
def readyz(request: Request, deep: bool = False) -> dict[str, Any]:
    """Readiness: version, commit, boot time, and the last database error seen; with
    deep=1, also a database round trip.

    A database that is still waking raises OperationalError, which the app turns into
    503 warming with Retry-After, the same answer every API route gives.
    """
    state = request.app.state
    body: dict[str, Any] = {
        "status": "ok",
        "version": __version__,
        "boot_at": state.boot_at.isoformat(),
        "commit": state.settings.git_commit,
        "last_db_error": state.last_db_error,
    }
    if deep:
        with state.sessions() as session:
            session.execute(text("SELECT 1"))
        body["database"] = "ok"
    return body
