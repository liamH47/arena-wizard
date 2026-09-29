"""Recorded results: wins and losses against a deck. PATCH is the only way to edit one."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Response

from arena_wizard.api.deps import DbSession, Now
from arena_wizard.api.schemas import RunCreate, RunUpdate, dump
from arena_wizard.auth.routes import CurrentUser
from arena_wizard.db import repository
from arena_wizard.db.models import DeckRunRow
from arena_wizard.web_build import body_hash

router = APIRouter(prefix="/api/runs")


def run_out(row: DeckRunRow) -> dict[str, Any]:
    """A run as the client sees it."""
    return {
        "id": row.id,
        "build_id": row.build_id,
        "deck_index": row.deck_index,
        "wins": row.wins,
        "losses": row.losses,
        "event_name": row.event_name,
        "notes": row.notes,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


@router.post("", status_code=201)
def create_run(
    body: RunCreate, user: CurrentUser, session: DbSession, now: Now, response: Response
) -> dict[str, Any]:
    """Record a result; an identical replay answers 200 and never undoes a later edit."""
    try:
        row, created = repository.create_run(
            session,
            user.user_id,
            str(body.id),
            body.build_id,
            body.deck_index,
            body.wins,
            body.losses,
            body.event_name,
            body.notes,
            body_hash(dump(body)),
            now,
        )
    except repository.NotFound as error:
        raise HTTPException(404, str(error)) from error
    except repository.Conflict as error:
        raise HTTPException(409, str(error)) from error
    if not created:
        response.status_code = 200
    return run_out(row)


@router.get("")
def list_runs(user: CurrentUser, session: DbSession) -> list[dict[str, Any]]:
    """The user's results, newest first."""
    return [run_out(row) for row in repository.list_runs(session, user.user_id)]


@router.patch("/{run_id}")
def update_run(
    run_id: str, body: RunUpdate, user: CurrentUser, session: DbSession, now: Now
) -> dict[str, Any]:
    """Change a result, for example 3-1 to 4-1 after another match."""
    try:
        row = repository.update_run(
            session,
            user.user_id,
            run_id,
            now,
            wins=body.wins,
            losses=body.losses,
            event_name=body.event_name,
            notes=body.notes,
        )
    except repository.NotFound as error:
        raise HTTPException(404, str(error)) from error
    return run_out(row)


@router.delete("/{run_id}", status_code=204)
def delete_run(run_id: str, user: CurrentUser, session: DbSession) -> None:
    """Delete one of the user's results."""
    try:
        repository.delete_run(session, user.user_id, run_id)
    except repository.NotFound as error:
        raise HTTPException(404, str(error)) from error
