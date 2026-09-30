"""Every database read and write, each answering "what happens if this runs twice?".

Personal data (pools, builds, runs) is always read through the owner's user id, so a
query that forgot it would not type-check and another user's row is indistinguishable
from a missing one. Pastes are the group's shared data (decision 0005's key has no user),
and record who pasted each.

Client-chosen ids make creates retry-safe: a replay of the same body returns the existing
row, while a different body, or another user's id, is a conflict and changes nothing.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from arena_wizard.db.models import (
    BuildRow,
    CardAdjustmentLog,
    CardAdjustmentRow,
    DeckRow,
    DeckRunRow,
    PasteDeletion,
    PasteRow,
    PoolRow,
    User,
)
from arena_wizard.domain.sets import EventType
from arena_wizard.engine.adjust import Adjustment
from arena_wizard.pastes.parsers import PARSER_VERSION, CardDataRow, GradeRow
from arena_wizard.pastes.sources import GRADES
from arena_wizard.pastes.store import PasteKey, StoredPaste


class NotFound(LookupError):
    """No such row for this user."""


class Conflict(ValueError):
    """The id is taken by a different body or another user; nothing changed."""


class InUse(ValueError):
    """The row is protected by another that depends on it; nothing changed."""


CONFLICT_MESSAGE = "someone else just pasted this key; reload and check before pasting"


class Forbidden(PermissionError):
    """The user may not do this to a row someone else owns."""


def upsert_user(
    session: Session,
    user_id: str,
    email: str,
    name: str,
    picture: str,
    now: dt.datetime,
    retry: bool = True,
) -> None:
    """Record a sign-in: create the user, or refresh their profile and last-seen time.

    Two first sign-ins at once both try to insert; the loser rereads and updates.
    """
    user = session.get(User, user_id)
    if user is None:
        session.add(
            User(
                user_id=user_id,
                email=email,
                name=name,
                picture=picture,
                created_at=now,
                last_seen_at=now,
            )
        )
    else:
        user.email, user.name, user.picture, user.last_seen_at = email, name, picture, now
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        if not retry:
            raise
        upsert_user(session, user_id, email, name, picture, now, False)


# ---- pools ------------------------------------------------------------------------------


def create_pool(
    session: Session,
    user_id: str,
    pool_id: str,
    set_code: str,
    fmt: str,
    raw_text: str,
    body_hash: str,
    pool_hash: str,
    now: dt.datetime,
    retry: bool = True,
) -> tuple[PoolRow, bool]:
    """Create a pool under the client's id, or return it on an identical replay.

    Returns:
        The pool, and whether this call created it.

    Raises:
        Conflict: The id exists with a different body or belongs to another user.
        IntegrityError: The insert failed for another reason (an unknown user), even
            after rereading once in case a concurrent request created the same id.
    """
    existing = session.get(PoolRow, pool_id)
    if existing is None:
        row = PoolRow(
            id=pool_id,
            user_id=user_id,
            set_code=set_code,
            format=fmt,
            raw_text=raw_text,
            body_hash=body_hash,
            pool_hash=pool_hash,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        try:
            session.commit()
        except IntegrityError:
            # Another request may have created the same id between our read and write.
            session.rollback()
            if not retry:
                raise
            return create_pool(
                session, user_id, pool_id, set_code, fmt, raw_text, body_hash, pool_hash, now, False
            )
        return row, True
    if existing.user_id != user_id or existing.body_hash != body_hash:
        raise Conflict(f"pool {pool_id} already exists with different contents")
    return existing, False


def list_pools(session: Session, user_id: str) -> list[PoolRow]:
    """A user's pools, newest first."""
    query = select(PoolRow).where(PoolRow.user_id == user_id)
    return list(session.scalars(query.order_by(PoolRow.created_at.desc(), PoolRow.id)))


def pools_with_builds(session: Session, user_id: str) -> set[str]:
    """Which of a user's pools have at least one build, for the home page's links."""
    query = (
        select(BuildRow.pool_id)
        .join(PoolRow, PoolRow.id == BuildRow.pool_id)
        .where(PoolRow.user_id == user_id)
        .distinct()
    )
    return set(session.scalars(query))


def get_pool(session: Session, user_id: str, pool_id: str) -> PoolRow:
    """One of the user's pools.

    Raises:
        NotFound: No such pool, or it is another user's.
    """
    row = session.get(PoolRow, pool_id)
    if row is None or row.user_id != user_id:
        raise NotFound(f"no pool {pool_id}")
    return row


def update_pool(
    session: Session,
    user_id: str,
    pool_id: str,
    raw_text: str,
    pool_hash: str,
    now: dt.datetime,
) -> PoolRow:
    """Replace a pool's text after the person edited it on the review screen.

    The create body's hash is kept, as runs keep theirs, so a replayed create still
    matches; the same text again changes nothing.
    """
    row = get_pool(session, user_id, pool_id)
    if row.raw_text != raw_text:
        row.raw_text, row.pool_hash, row.updated_at = raw_text, pool_hash, now
        session.commit()
    return row


def delete_pool(session: Session, user_id: str, pool_id: str) -> None:
    """Delete a pool with its builds and decks.

    Raises:
        NotFound: No such pool for this user.
        InUse: A run was recorded against one of its decks; nothing was deleted.
    """
    row = get_pool(session, user_id, pool_id)
    session.delete(row)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise InUse(f"pool {pool_id} has recorded runs; delete those first") from None


# ---- builds -----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class NewDeck:
    """A deck to store with its build."""

    colors: str
    splash: str | None
    total: float
    total_se: float
    payload: dict[str, Any]


def find_build(session: Session, pool_id: str, inputs_key: str) -> BuildRow | None:
    """The build already made from exactly these inputs, if any."""
    query = select(BuildRow).where(BuildRow.pool_id == pool_id, BuildRow.inputs_key == inputs_key)
    return session.scalars(query).first()


def save_build(
    session: Session,
    pool_id: str,
    inputs_key: str,
    config_version: str,
    mode: str,
    data_lines: Sequence[str],
    refusal: str | None,
    decks: Sequence[NewDeck],
    now: dt.datetime,
    retry: bool = True,
) -> BuildRow:
    """Store a build and its decks in one transaction, or return the one already there.

    Raises:
        IntegrityError: The insert failed for another reason (an unknown pool), even after
            rereading once in case a concurrent request stored the same build.
    """
    found = find_build(session, pool_id, inputs_key)
    if found is not None:
        return found
    build = BuildRow(
        pool_id=pool_id,
        inputs_key=inputs_key,
        config_version=config_version,
        mode=mode,
        data_lines=list(data_lines),
        refusal=refusal,
        created_at=now,
    )
    session.add(build)
    try:
        session.flush()
        for index, deck in enumerate(decks):
            session.add(
                DeckRow(
                    build_id=build.id,
                    deck_index=index,
                    colors=deck.colors,
                    splash=deck.splash,
                    total=deck.total,
                    total_se=deck.total_se,
                    payload=deck.payload,
                )
            )
        session.commit()
    except IntegrityError:
        session.rollback()
        if not retry:
            raise
        return save_build(
            session,
            pool_id,
            inputs_key,
            config_version,
            mode,
            data_lines,
            refusal,
            decks,
            now,
            False,
        )
    return build


def latest_build(session: Session, user_id: str, pool_id: str) -> BuildRow | None:
    """The user's most recent build of a pool."""
    get_pool(session, user_id, pool_id)
    query = select(BuildRow).where(BuildRow.pool_id == pool_id)
    return session.scalars(query.order_by(BuildRow.id.desc())).first()


def decks_of(session: Session, build_id: int) -> list[DeckRow]:
    """A build's decks in rank order."""
    query = select(DeckRow).where(DeckRow.build_id == build_id)
    return list(session.scalars(query.order_by(DeckRow.deck_index)))


# ---- runs -------------------------------------------------------------------------------


def _owned_deck(session: Session, user_id: str, build_id: int, deck_index: int) -> DeckRow:
    deck = session.get(DeckRow, (build_id, deck_index))
    build = session.get(BuildRow, build_id) if deck else None
    pool = session.get(PoolRow, build.pool_id) if build else None
    if deck is None or pool is None or pool.user_id != user_id:
        raise NotFound(f"no deck {build_id}/{deck_index}")
    return deck


def create_run(
    session: Session,
    user_id: str,
    run_id: str,
    build_id: int,
    deck_index: int,
    wins: int,
    losses: int,
    event_name: str,
    notes: str,
    body_hash: str,
    now: dt.datetime,
    retry: bool = True,
) -> tuple[DeckRunRow, bool]:
    """Record a result under the client's id, or return it on an identical replay.

    A replayed create never undoes a later edit: once the run exists, only its own body
    hash counts, and a PATCH changes the row, not the hash of the original create.

    Raises:
        NotFound: The deck is not one of this user's.
        Conflict: The id exists with a different body or belongs to another user.
        IntegrityError: The insert failed for another reason, even after rereading once.
    """
    existing = session.get(DeckRunRow, run_id)
    if existing is None:
        _owned_deck(session, user_id, build_id, deck_index)
        row = DeckRunRow(
            id=run_id,
            user_id=user_id,
            build_id=build_id,
            deck_index=deck_index,
            wins=wins,
            losses=losses,
            event_name=event_name,
            notes=notes,
            extra={},
            body_hash=body_hash,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            if not retry:
                raise
            return create_run(
                session,
                user_id,
                run_id,
                build_id,
                deck_index,
                wins,
                losses,
                event_name,
                notes,
                body_hash,
                now,
                False,
            )
        return row, True
    if existing.user_id != user_id or existing.body_hash != body_hash:
        raise Conflict(f"run {run_id} already exists with different contents")
    return existing, False


def list_runs(session: Session, user_id: str) -> list[DeckRunRow]:
    """A user's recorded runs, newest first."""
    query = select(DeckRunRow).where(DeckRunRow.user_id == user_id)
    return list(session.scalars(query.order_by(DeckRunRow.created_at.desc(), DeckRunRow.id)))


def get_run(session: Session, user_id: str, run_id: str) -> DeckRunRow:
    """One of the user's runs.

    Raises:
        NotFound: No such run, or it is another user's.
    """
    row = session.get(DeckRunRow, run_id)
    if row is None or row.user_id != user_id:
        raise NotFound(f"no run {run_id}")
    return row


def update_run(
    session: Session,
    user_id: str,
    run_id: str,
    now: dt.datetime,
    wins: int | None = None,
    losses: int | None = None,
    event_name: str | None = None,
    notes: str | None = None,
) -> DeckRunRow:
    """Change a run's fields; the only way a recorded run is ever modified."""
    row = get_run(session, user_id, run_id)
    changes = {"wins": wins, "losses": losses, "event_name": event_name, "notes": notes}
    changed = False
    for field, value in changes.items():
        if value is not None and getattr(row, field) != value:
            setattr(row, field, value)
            changed = True
    if changed:
        row.updated_at = now
        session.commit()
    return row


def delete_run(session: Session, user_id: str, run_id: str) -> None:
    """Delete one of the user's runs."""
    session.delete(get_run(session, user_id, run_id))
    session.commit()


# ---- pastes -----------------------------------------------------------------------------


def _event_column(event_type: EventType | None) -> str:
    return event_type.value if event_type else GRADES


def _rows_json(paste: StoredPaste) -> list[Any]:
    if paste.key.dataset == GRADES:
        return [[r.name, r.raw, r.value] for r in paste.grade_rows]
    return [
        [r.name, r.color, r.rarity, r.games_gih, r.gih_wr, r.games_gns, r.gns_wr]
        for r in paste.card_rows
    ]


def stored_pastes(session: Session, set_code: str) -> tuple[list[StoredPaste], list[str]]:
    """A set's pastes as engine objects, and a message for each from an older parser.

    Stale pastes are left out and named, mirroring the CLI's file store: a parser fix must
    never silently keep using rows the old parser produced (decision 0007 item 18).
    """
    pastes: list[StoredPaste] = []
    problems: list[str] = []
    for row in list_paste_rows(session, set_code):
        if row.parser_version != PARSER_VERSION:
            problems.append(
                f"{row.label} from {row.import_day} was stored by an older version; paste it again"
            )
        else:
            pastes.append(to_stored(row))
    return pastes, problems


def to_stored(row: PasteRow) -> StoredPaste:
    """A database row as the engine's paste object."""
    event = None if row.event_type == GRADES else EventType(row.event_type)
    grades = row.dataset == GRADES
    return StoredPaste(
        key=PasteKey(row.set_code, row.dataset, event, row.source_id, row.import_day),
        label=row.label,
        url=row.url,
        copied_on=row.copied_on,
        published_on=row.published_on,
        columns=tuple(row.columns),
        text_sha256=row.text_sha256,
        parser_version=row.parser_version,
        card_rows=() if grades else tuple(CardDataRow(*r) for r in row.rows),
        grade_rows=tuple(GradeRow(*r) for r in row.rows) if grades else (),
    )


def _find_paste(session: Session, key: PasteKey) -> PasteRow | None:
    query = select(PasteRow).where(
        PasteRow.set_code == key.set_code,
        PasteRow.dataset == key.dataset,
        PasteRow.event_type == _event_column(key.event_type),
        PasteRow.source_id == key.source_id,
        PasteRow.import_day == key.import_day,
    )
    return session.scalars(query).first()


def stored_sha(session: Session, key: PasteKey) -> str | None:
    """The text hash stored under a key now, whatever parser stored it; None when empty."""
    row = _find_paste(session, key)
    return row.text_sha256 if row is not None else None


def list_paste_rows(session: Session, set_code: str) -> list[PasteRow]:
    """Every paste for a set, in key order."""
    query = select(PasteRow).where(PasteRow.set_code == set_code)
    return list(
        session.scalars(
            query.order_by(
                PasteRow.dataset, PasteRow.event_type, PasteRow.source_id, PasteRow.import_day
            )
        )
    )


def save_paste(
    session: Session,
    paste: StoredPaste,
    user_id: str,
    now: dt.datetime,
    expected_sha: str | None,
    retry: bool = True,
) -> bool:
    """Store a paste under its key, replacing that day's paste. Idempotent.

    Args:
        session: The database session.
        paste: The checked paste.
        user_id: Who pasted it.
        now: When.
        expected_sha: The stored paste's text hash when the paste was checked (None when
            there was none). If another friend pasted the same key since, nothing changes.
        retry: Internal: whether a failed insert may reread once.

    Returns:
        False when an identical paste was already stored and nothing changed.

    Raises:
        Conflict: Someone else pasted this key after it was checked.
        IntegrityError: The insert failed for another reason (an unknown user).
    """
    fields = {
        "label": paste.label,
        "url": paste.url,
        "copied_on": paste.copied_on,
        "published_on": paste.published_on,
        "columns": list(paste.columns),
        "rows": _rows_json(paste),
        "text_sha256": paste.text_sha256,
        "parser_version": paste.parser_version,
    }
    row = _find_paste(session, paste.key)
    if row is not None and all(getattr(row, name) == value for name, value in fields.items()):
        return False
    current = row.text_sha256 if row is not None else None
    if current != expected_sha:
        raise Conflict(CONFLICT_MESSAGE)
    if row is not None:
        # The database checks the hash again inside the UPDATE, so a friend who pasted
        # between our read and this write wins, and this paste changes nothing.
        result = session.execute(
            update(PasteRow)
            .where(PasteRow.id == row.id, PasteRow.text_sha256 == expected_sha)
            .values(**fields, pasted_by=user_id, replaced_at=now)
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:  # type: ignore[attr-defined]
            session.rollback()
            raise Conflict(CONFLICT_MESSAGE)
        session.commit()
        session.expire_all()
        return True
    session.add(
        PasteRow(
            set_code=paste.key.set_code,
            dataset=paste.key.dataset,
            event_type=_event_column(paste.key.event_type),
            source_id=paste.key.source_id,
            import_day=paste.key.import_day,
            pasted_by=user_id,
            pasted_at=now,
            replaced_at=None,
            **fields,
        )
    )
    try:
        session.commit()
    except IntegrityError:
        # A concurrent paste of the same key may have won; the reread reports it.
        session.rollback()
        if not retry:
            raise
        return save_paste(session, paste, user_id, now, expected_sha, False)
    return True


def delete_paste_row(
    session: Session, key: PasteKey, user_id: str, is_owner: bool, now: dt.datetime
) -> bool:
    """Retract a paste, logging who did it but not the data (decision 0008).

    Returns:
        False when there was no such paste.

    Raises:
        Forbidden: Only whoever last pasted it, or the owner, may delete a paste.
    """
    row = _find_paste(session, key)
    if row is None:
        return False
    if row.pasted_by != user_id and not is_owner:
        raise Forbidden("only whoever pasted this, or the owner, may delete it")
    session.add(
        PasteDeletion(
            set_code=row.set_code,
            dataset=row.dataset,
            event_type=row.event_type,
            source_id=row.source_id,
            import_day=row.import_day,
            pasted_by=row.pasted_by,
            deleted_by=user_id,
            deleted_at=now,
        )
    )
    session.delete(row)
    session.commit()
    return True


# ---- card adjustments -------------------------------------------------------------------


def adjustment_rows(session: Session, set_code: str) -> list[tuple[CardAdjustmentRow, str]]:
    """A set's adjustments by card name, each with the name of who last changed it."""
    rows = session.execute(
        select(CardAdjustmentRow, User)
        .join(User, User.user_id == CardAdjustmentRow.updated_by)
        .where(CardAdjustmentRow.set_code == set_code)
        .order_by(CardAdjustmentRow.name)
    )
    return [(row, user.name or user.email.split("@")[0]) for row, user in rows]


def list_adjustments(session: Session, set_code: str) -> list[Adjustment]:
    """A set's adjustments as the engine applies them."""
    return [
        Adjustment(r.name, r.bomb, r.q_delta, r.note, by)
        for r, by in adjustment_rows(session, set_code)
    ]


def set_adjustment(
    session: Session,
    set_code: str,
    name: str,
    bomb: str | None,
    q_delta: float | None,
    note: str,
    user_id: str,
    now: dt.datetime,
) -> bool:
    """Set a card's adjustment and log it; False when nothing changed. Last writer wins."""
    row = session.scalars(
        select(CardAdjustmentRow).where(
            CardAdjustmentRow.set_code == set_code, CardAdjustmentRow.name == name
        )
    ).first()
    if row is not None and (row.bomb, row.q_delta, row.note) == (bomb, q_delta, note):
        return False
    if row is None:
        row = CardAdjustmentRow(set_code=set_code, name=name)
        session.add(row)
    row.bomb, row.q_delta, row.note, row.updated_by, row.updated_at = (
        bomb,
        q_delta,
        note,
        user_id,
        now,
    )
    _log(session, set_code, name, "set", bomb, q_delta, note, user_id, now)
    session.commit()
    return True


def clear_adjustment(
    session: Session, set_code: str, name: str, user_id: str, now: dt.datetime
) -> bool:
    """Remove a card's adjustment and log it; False when there was none."""
    row = session.scalars(
        select(CardAdjustmentRow).where(
            CardAdjustmentRow.set_code == set_code, CardAdjustmentRow.name == name
        )
    ).first()
    if row is None:
        return False
    session.delete(row)
    _log(session, set_code, name, "clear", None, None, "", user_id, now)
    session.commit()
    return True


def _log(
    session: Session,
    set_code: str,
    name: str,
    action: str,
    bomb: str | None,
    q_delta: float | None,
    note: str,
    user_id: str,
    now: dt.datetime,
) -> None:
    session.add(
        CardAdjustmentLog(
            set_code=set_code,
            name=name,
            action=action,
            bomb=bomb,
            q_delta=q_delta,
            note=note,
            changed_by=user_id,
            changed_at=now,
        )
    )
