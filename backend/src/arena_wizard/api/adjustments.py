"""The group's card adjustments (decision 0011): any friend may add or remove a bomb or nudge
a card's value, and every change is logged with who made it."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Response

from arena_wizard.api.deps import DbSession, Now
from arena_wizard.api.schemas import AdjustmentSet
from arena_wizard.auth.routes import CurrentUser
from arena_wizard.catalog import load_packaged_card_table
from arena_wizard.db import repository
from arena_wizard.domain.sets import ConfigError, load_set_config
from arena_wizard.engine.values import spell_rarities

router = APIRouter(prefix="/api/adjustments")


def _spell(set_code: str, name: str) -> str:
    try:
        code = load_set_config(set_code.upper()).code
    except (ConfigError, FileNotFoundError) as error:
        raise HTTPException(422, f"unknown set {set_code}") from error
    if name not in spell_rarities(load_packaged_card_table(code).cards):
        raise HTTPException(422, f"{name} is not a spell in {code}")
    return code


@router.get("")
def list_adjustments(set_code: str, user: CurrentUser, session: DbSession) -> list[dict[str, Any]]:
    """Every adjustment for a set, with who made it and when."""
    return [
        {
            "name": row.name,
            "bomb": row.bomb,
            "q_delta": row.q_delta,
            "note": row.note,
            "by": by,
            "updated_at": row.updated_at.isoformat(),
        }
        for row, by in repository.adjustment_rows(session, set_code.upper())
    ]


@router.put("/{set_code}/{name:path}")
def set_adjustment(
    set_code: str, name: str, body: AdjustmentSet, user: CurrentUser, session: DbSession, now: Now
) -> dict[str, bool]:
    """Set a card's adjustment; `changed` is false when it already said this."""
    code = _spell(set_code, name)
    changed = repository.set_adjustment(
        session, code, name, body.bomb, body.q_delta, body.note, user.user_id, now
    )
    return {"changed": changed}


@router.delete("/{set_code}/{name:path}", status_code=204)
def clear_adjustment(
    set_code: str, name: str, user: CurrentUser, session: DbSession, now: Now
) -> Response:
    """Clear a card's adjustment; clearing one that is not there is a no-op."""
    repository.clear_adjustment(session, _spell(set_code, name), name, user.user_id, now)
    return Response(status_code=204)
