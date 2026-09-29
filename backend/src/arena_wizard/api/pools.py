"""Pools and their builds: paste an export, review it, build decks, fetch the latest build.

Every route is scoped to the signed-in user; another user's pool is a 404, and reusing
another user's pool id is a 409 that changes nothing.
"""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, HTTPException, Response

from arena_wizard.api.deps import DbSession, Now
from arena_wizard.api.schemas import PoolCreate, PoolUpdate, dump
from arena_wizard.auth.routes import CurrentUser
from arena_wizard.datadir import utc_day
from arena_wizard.db import repository
from arena_wizard.db.models import BuildRow, PoolRow
from arena_wizard.domain.pool import Pool
from arena_wizard.domain.sets import ConfigError, Format, load_set_config
from arena_wizard.pastes.store import StoredPaste
from arena_wizard.web_build import (
    body_hash,
    deck_payload,
    inputs_key,
    pool_hash,
    resolve_export,
    run_build,
)

router = APIRouter(prefix="/api/pools")
CARD_LINE = re.compile(r"^\d+\s+\S")


def _format(value: str) -> Format:
    if value != Format.BO1_SEALED.value:
        raise HTTPException(422, "only bo1_sealed has a scoring configuration")
    return Format(value)


def _resolve(set_code: str, fmt: str, text: str) -> Pool:
    try:
        config = load_set_config(set_code.upper())
    except (ConfigError, FileNotFoundError) as error:
        raise HTTPException(422, f"unknown set {set_code}") from error
    return resolve_export(config, _format(fmt), text)


def pool_out(row: PoolRow) -> dict[str, Any]:
    """A pool with its resolved cards, warnings, and the set's usual pool size."""
    pool = _resolve(row.set_code, row.format, row.raw_text)
    low, high = load_set_config(row.set_code).nonbasic_pool_range
    return {
        "id": row.id,
        "set_code": row.set_code,
        "format": row.format,
        "export_text": row.raw_text,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
        "nonbasic_count": pool.nonbasic_count,
        "usual_range": [low, high],
        "entries": [
            {
                "name": e.card.front_name,
                "count": e.count,
                "set_code": e.card.set_code,
                "collector_number": e.card.collector_number,
                "rarity": e.card.rarity.value,
                "colors": "".join(c.value for c in e.card.colors),
                "mana_cost": e.card.mana_cost,
                "type_line": e.card.type_line,
                "image_uri": e.card.image_uri,
            }
            for e in pool.entries
        ],
        "basics": [{"name": e.card.front_name, "count": e.count} for e in pool.basics],
        "warnings": [
            {
                "kind": w.kind.value,
                "message": w.message,
                "line_no": w.line_no,
                "raw": w.raw,
                "suggestions": list(w.suggestions),
            }
            for w in pool.warnings
        ],
    }


def build_out(session: DbSession, build: BuildRow, current: bool) -> dict[str, Any]:
    """A build with its Data block and decks, and whether it matches the pool's inputs now."""
    return {
        "id": build.id,
        "current": current,
        "pool_id": build.pool_id,
        "mode": build.mode,
        "config_version": build.config_version,
        "created_at": build.created_at.isoformat(),
        "data_lines": build.data_lines,
        "refusal": build.refusal,
        "decks": [
            {"deck_index": d.deck_index, **d.payload}
            for d in repository.decks_of(session, build.id)
        ],
    }


def _not_found(error: repository.NotFound) -> HTTPException:
    return HTTPException(404, str(error))


@router.post("", status_code=201)
def create_pool(
    body: PoolCreate, user: CurrentUser, session: DbSession, now: Now, response: Response
) -> dict[str, Any]:
    """Create a pool; an identical replay answers 200 with the same pool."""
    pool = _resolve(body.set_code, body.format, body.export_text)
    try:
        row, created = repository.create_pool(
            session,
            user.user_id,
            str(body.id),
            pool.set_code,
            body.format,
            body.export_text,
            body_hash(dump(body)),
            pool_hash(pool),
            now,
        )
    except repository.Conflict as error:
        raise HTTPException(409, str(error)) from error
    if not created:
        response.status_code = 200
    return pool_out(row)


@router.get("")
def list_pools(user: CurrentUser, session: DbSession) -> list[dict[str, Any]]:
    """The user's pools, newest first, without their card lists.

    `has_build` lets the home page open a built pool straight at its decks, and `hint` is
    the first card line of the export, so pools of the same set can be told apart.
    """
    built = repository.pools_with_builds(session, user.user_id)
    return [
        {
            "id": row.id,
            "set_code": row.set_code,
            "format": row.format,
            "created_at": row.created_at.isoformat(),
            "updated_at": row.updated_at.isoformat(),
            "has_build": row.id in built,
            "hint": _hint(row.raw_text),
        }
        for row in repository.list_pools(session, user.user_id)
    ]


HINT_CHARS = 48


def _hint(text: str) -> str:
    """The first card line of an export, shortened; empty when there is none."""
    line = next((line.strip() for line in text.splitlines() if CARD_LINE.match(line.strip())), "")
    return line if len(line) <= HINT_CHARS else line[: HINT_CHARS - 1] + "…"


@router.get("/{pool_id}")
def get_pool(pool_id: str, user: CurrentUser, session: DbSession) -> dict[str, Any]:
    """One pool, resolved for the review screen."""
    try:
        return pool_out(repository.get_pool(session, user.user_id, pool_id))
    except repository.NotFound as error:
        raise _not_found(error) from error


@router.put("/{pool_id}")
def update_pool(
    pool_id: str, body: PoolUpdate, user: CurrentUser, session: DbSession, now: Now
) -> dict[str, Any]:
    """Replace a pool's export text after edits on the review screen."""
    try:
        row = repository.get_pool(session, user.user_id, pool_id)
        pool = _resolve(row.set_code, row.format, body.export_text)
        row = repository.update_pool(
            session, user.user_id, pool_id, body.export_text, pool_hash(pool), now
        )
    except repository.NotFound as error:
        raise _not_found(error) from error
    return pool_out(row)


@router.delete("/{pool_id}", status_code=204)
def delete_pool(pool_id: str, user: CurrentUser, session: DbSession) -> None:
    """Delete a pool and its builds; refused while a recorded run points at one of them."""
    try:
        repository.delete_pool(session, user.user_id, pool_id)
    except repository.NotFound as error:
        raise _not_found(error) from error
    except repository.InUse as error:
        raise HTTPException(409, str(error)) from error


def _current(
    session: DbSession, row: PoolRow, now: Now
) -> tuple[Pool, list[StoredPaste], list[str], str]:
    """The pool as it stands now, the pastes a build would use, and its inputs key."""
    pool = _resolve(row.set_code, row.format, row.raw_text)
    pastes, stale = repository.stored_pastes(session, row.set_code)
    return pool, pastes, stale, inputs_key(pool, pastes, utc_day(now))


@router.post("/{pool_id}/builds")
def build(
    pool_id: str, user: CurrentUser, session: DbSession, now: Now, response: Response
) -> dict[str, Any]:
    """Build decks, or return the existing build when nothing it depends on has changed."""
    try:
        row = repository.get_pool(session, user.user_id, pool_id)
    except repository.NotFound as error:
        raise _not_found(error) from error
    pool, pastes, stale, key = _current(session, row, now)
    existing = repository.find_build(session, pool_id, key)
    if existing is not None:
        return build_out(session, existing, current=True)
    mode, result, version = run_build(pool, pastes, utc_day(now), stale)
    decks = [
        repository.NewDeck(
            colors=d.colors,
            splash=d.splash.value if d.splash else None,
            total=d.total,
            total_se=d.total_se,
            payload=deck_payload(d),
        )
        for d in result.decks
    ]
    saved = repository.save_build(
        session, pool_id, key, version, mode, result.data_lines, result.refusal, decks, now
    )
    response.status_code = 201
    return build_out(session, saved, current=True)


@router.get("/{pool_id}/builds/latest")
def latest_build(pool_id: str, user: CurrentUser, session: DbSession, now: Now) -> dict[str, Any]:
    """The build for the pool as it stands now, or the newest one marked not current.

    "Newest" alone would show decks from text or pastes that no longer exist, for example
    after an edit is reverted or a paste is deleted (decision 0008).
    """
    try:
        row = repository.get_pool(session, user.user_id, pool_id)
    except repository.NotFound as error:
        raise _not_found(error) from error
    *_, key = _current(session, row, now)
    found = repository.find_build(session, pool_id, key)
    if found is not None:
        return build_out(session, found, current=True)
    newest = repository.latest_build(session, user.user_id, pool_id)
    if newest is None:
        raise HTTPException(404, f"pool {pool_id} has no build yet")
    return build_out(session, newest, current=False)
