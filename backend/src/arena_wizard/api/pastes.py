"""Hand-pasted data for the group (decisions 0005 and 0007), stored in the database.

The same checks as the CLI's `paste`: nothing is stored unless every check passes, one
paste per set, dataset, event type, source, and UTC day, and a paste's link is a label
that the server never fetches. Pastes are shared by the group and record who pasted.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response

from arena_wizard.api.deps import DbSession, Now
from arena_wizard.api.schemas import PasteCreate
from arena_wizard.auth.routes import CurrentUser
from arena_wizard.cli import decode_text
from arena_wizard.config import Settings
from arena_wizard.datadir import utc_day
from arena_wizard.db import repository
from arena_wizard.db.models import PasteRow
from arena_wizard.domain.sets import ConfigError, EventType, load_set_config
from arena_wizard.paste_commands import PasteRejected, PasteRequest, outcome_lines, plan_paste
from arena_wizard.pastes.sources import GRADES, REGISTRY, UnknownSource, source_for
from arena_wizard.pastes.store import PasteKey
from arena_wizard.web_build import covered

router = APIRouter(prefix="/api/pastes")


def paste_out(row: PasteRow) -> dict[str, Any]:
    """A stored paste's key and labels; its rows stay on the server."""
    return {
        "key": f"{row.dataset}/{row.event_type}/{row.source_id}/{row.import_day}",
        "set_code": row.set_code,
        "dataset": row.dataset,
        "event_type": None if row.event_type == GRADES else row.event_type,
        "source_id": row.source_id,
        "label": row.label,
        "import_day": row.import_day.isoformat(),
        "copied_on": row.copied_on.isoformat(),
        "published_on": row.published_on.isoformat() if row.published_on else None,
        "rows": len(row.rows),
        "pasted_by": row.pasted_by,
        "replaced_at": row.replaced_at.isoformat() if row.replaced_at else None,
    }


@router.get("/sources")
def sources(user: CurrentUser) -> list[dict[str, str]]:
    """The registered sources a paste may name; `own-<name>` is also accepted for grades."""
    return [{"id": s.id, "label": s.label, "dataset": s.dataset} for s in REGISTRY.values()]


@router.get("")
def list_pastes(set_code: str, user: CurrentUser, session: DbSession) -> list[dict[str, Any]]:
    """Every paste for a set."""
    return [paste_out(row) for row in repository.list_paste_rows(session, set_code.upper())]


@router.post("", status_code=201)
def create_paste(
    body: PasteCreate, user: CurrentUser, session: DbSession, now: Now, response: Response
) -> dict[str, Any]:
    """Check and store a paste; 422 with the reason when any check fails."""
    try:
        config = load_set_config(body.set_code.upper())
        event = EventType(body.event_type) if body.event_type else None
    except (ConfigError, FileNotFoundError, ValueError) as error:
        raise HTTPException(422, f"unknown set or event type: {error}") from error
    request = PasteRequest(
        set_code=config.code,
        dataset=body.dataset,
        source_id=body.source_id,
        event_type=event,
        copied_on=body.copied_on,
        published_on=body.published_on,
        url=body.url,
        replace=body.replace,
    )
    today = utc_day(now)
    stored, _ = repository.stored_pastes(session, config.code)
    try:
        plan = plan_paste(
            request,
            body.text.encode("utf-8"),
            config,
            today,
            covered(config, today),
            stored,
            decode_text,
        )
    except PasteRejected as error:
        raise HTTPException(422, f"Refused, nothing stored: {error}.") from error
    # From the row itself: a paste an older parser stored is left out of `stored`, but it
    # still holds the key, and re-pasting it is how it gets replaced.
    expected = repository.stored_sha(session, plan.new.key)
    try:
        written = repository.save_paste(session, plan.new, user.user_id, now, expected)
    except repository.Conflict as error:
        raise HTTPException(409, str(error)) from error
    if not written:
        response.status_code = 200
    return {"messages": outcome_lines(plan, written, "for the group", request, web=True)}


@router.delete("/{set_code}/{dataset}/{kind}/{source_id}/{day}", status_code=204)
def delete_paste(
    set_code: str,
    dataset: str,
    kind: str,
    source_id: str,
    day: dt.date,
    user: CurrentUser,
    session: DbSession,
    now: Now,
    request: Request,
) -> None:
    """Retract a paste: whoever last pasted it, or the owner (decision 0008)."""
    try:
        key = PasteKey(
            set_code.upper(),
            dataset,
            None if kind == GRADES else EventType(kind),
            source_for(source_id).id,
            day,
        )
    except (ValueError, UnknownSource) as error:
        raise HTTPException(404, f"no such paste: {error}") from error
    settings: Settings = request.app.state.settings
    is_owner = settings.auth == "off" or user.email == settings.owner_email
    try:
        deleted = repository.delete_paste_row(session, key, user.user_id, is_owner, now)
    except repository.Forbidden as error:
        raise HTTPException(403, str(error)) from error
    if not deleted:
        raise HTTPException(404, "no such paste")
