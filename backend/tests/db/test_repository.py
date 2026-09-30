from __future__ import annotations

import dataclasses
import datetime as dt
from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import ORMExecuteState, Session, sessionmaker

from arena_wizard.db import repository
from arena_wizard.db.models import (
    BuildRow,
    CardAdjustmentLog,
    DeckRow,
    DeckRunRow,
    PasteDeletion,
    PasteRow,
    PoolRow,
    User,
)
from arena_wizard.domain.sets import EventType
from arena_wizard.pastes.parsers import CardDataRow, GradeRow
from arena_wizard.pastes.store import PasteKey, StoredPaste
from tests.db.conftest import LATER, NOW

POOL = "11111111-1111-1111-1111-111111111111"
RUN = "22222222-2222-2222-2222-222222222222"
DAY = dt.date(2026, 10, 3)


def _pool(session: Session, user: str = "alice", body: str = "h1", **kw: Any) -> Any:
    return repository.create_pool(
        session, user, kw.pop("pool_id", POOL), "FRA", "bo1_sealed", "1 Card", body, "p1", NOW, **kw
    )


def _deck(index: int = 0) -> repository.NewDeck:
    return repository.NewDeck("WU", None, 10.0 + index, 1.0, {"label": f"deck {index}"})


def _build(session: Session, key: str = "k1", decks: int = 2, **kw: Any) -> BuildRow:
    return repository.save_build(
        session,
        kw.pop("pool_id", POOL),
        key,
        "0.3",
        "event",
        ["line"],
        None,
        [_deck(i) for i in range(decks)],
        NOW,
        **kw,
    )


def _run(session: Session, build_id: int, user: str = "alice", body: str = "r1", **kw: Any) -> Any:
    return repository.create_run(
        session, user, kw.pop("run_id", RUN), build_id, 0, 3, 1, "Direct", "", body, NOW, **kw
    )


def _count(session: Session, model: type[Any]) -> int:
    return session.scalar(select(func.count()).select_from(model)) or 0


def _race(
    session: Session, sessions: sessionmaker[Session], insert: Callable[[Session], object]
) -> None:
    """Before `session` next flushes, another session commits `insert`: a concurrent request
    that won the race between our read and our write."""

    def before_flush(*_: Any) -> None:
        with sessions() as other:
            insert(other)
            other.commit()

    event.listen(session, "before_flush", before_flush, once=True)


# ---- users ------------------------------------------------------------------------------


def test_two_first_sign_ins_at_once_both_succeed(
    session: Session, sessions: sessionmaker[Session]
) -> None:
    _race(
        session,
        sessions,
        lambda other: repository.upsert_user(other, "carol", "c@example.com", "C", "", NOW),
    )
    repository.upsert_user(session, "carol", "carol@example.com", "Carol", "", LATER)
    user = session.get(User, "carol")
    assert user is not None and (user.email, user.last_seen_at) == ("carol@example.com", LATER)


def test_a_sign_in_that_still_conflicts_on_the_reread_raises(
    session: Session, sessions: sessionmaker[Session]
) -> None:
    _race(
        session,
        sessions,
        lambda other: repository.upsert_user(other, "dave", "d@example.com", "D", "", NOW),
    )
    with pytest.raises(IntegrityError):
        repository.upsert_user(session, "dave", "d@example.com", "D", "", LATER, retry=False)


def test_signing_in_again_refreshes_the_profile_without_a_second_user(session: Session) -> None:
    repository.upsert_user(session, "alice", "new@example.com", "Alice B", "pic", LATER)
    user = session.get(User, "alice")
    assert user is not None
    assert (user.email, user.name, user.picture) == ("new@example.com", "Alice B", "pic")
    assert user.created_at == NOW and user.last_seen_at == LATER
    assert _count(session, User) == 2


# ---- pools ------------------------------------------------------------------------------


def test_creating_a_pool_twice_with_the_same_body_stores_one_row(session: Session) -> None:
    first, created = _pool(session)
    again, created_again = _pool(session)
    assert created and not created_again
    assert again.id == first.id and _count(session, PoolRow) == 1


@pytest.mark.parametrize(("user", "body"), [("alice", "h2"), ("bob", "h1")])
def test_a_different_body_or_another_user_is_a_conflict_that_changes_nothing(
    session: Session, user: str, body: str
) -> None:
    _pool(session)
    with pytest.raises(repository.Conflict):
        _pool(session, user=user, body=body)
    row = session.get(PoolRow, POOL)
    assert row is not None and (row.user_id, row.body_hash) == ("alice", "h1")


def test_a_pool_for_an_unknown_user_fails_after_exactly_one_reread(session: Session) -> None:
    with pytest.raises(IntegrityError):
        _pool(session, user="nobody")
    assert _count(session, PoolRow) == 0


def test_a_pool_created_concurrently_with_the_same_body_is_returned(
    session: Session, sessions: sessionmaker[Session]
) -> None:
    _race(
        session,
        sessions,
        lambda other: other.add(
            PoolRow(
                id=POOL,
                user_id="alice",
                set_code="FRA",
                format="bo1_sealed",
                raw_text="1 Card",
                body_hash="h1",
                pool_hash="p1",
                created_at=NOW,
                updated_at=NOW,
            )
        ),
    )
    row, created = _pool(session)
    assert not created and row.id == POOL and _count(session, PoolRow) == 1


def test_pools_are_listed_newest_first_and_only_the_owners(session: Session) -> None:
    _pool(session)
    repository.create_pool(
        session,
        "alice",
        "33333333-3333-3333-3333-333333333333",
        "FRA",
        "bo1_sealed",
        "x",
        "h9",
        "p9",
        LATER,
    )
    repository.create_pool(
        session,
        "bob",
        "44444444-4444-4444-4444-444444444444",
        "FRA",
        "bo1_sealed",
        "x",
        "h8",
        "p8",
        LATER,
    )
    assert [p.id for p in repository.list_pools(session, "alice")] == [
        "33333333-3333-3333-3333-333333333333",
        POOL,
    ]


def test_another_users_pool_is_not_found(session: Session) -> None:
    _pool(session)
    with pytest.raises(repository.NotFound):
        repository.get_pool(session, "bob", POOL)
    with pytest.raises(repository.NotFound):
        repository.get_pool(session, "alice", "missing")


def test_updating_a_pool_changes_it_only_when_the_text_changed(session: Session) -> None:
    _pool(session)
    same = repository.update_pool(session, "alice", POOL, "1 Card", "p2", LATER)
    assert (same.raw_text, same.pool_hash, same.updated_at) == ("1 Card", "p1", NOW)
    changed = repository.update_pool(session, "alice", POOL, "2 Card", "p2", LATER)
    assert (changed.raw_text, changed.pool_hash, changed.updated_at) == ("2 Card", "p2", LATER)
    assert changed.body_hash == "h1"
    replayed, created = _pool(session)
    assert not created and replayed.raw_text == "2 Card"


def test_deleting_a_pool_takes_its_builds_and_decks(session: Session) -> None:
    _pool(session)
    _build(session)
    repository.delete_pool(session, "alice", POOL)
    assert [_count(session, m) for m in (PoolRow, BuildRow, DeckRow)] == [0, 0, 0]


def test_a_pool_with_a_recorded_run_cannot_be_deleted(session: Session) -> None:
    _pool(session)
    build = _build(session)
    _run(session, build.id)
    with pytest.raises(repository.InUse):
        repository.delete_pool(session, "alice", POOL)
    counts = [_count(session, m) for m in (PoolRow, BuildRow, DeckRow, DeckRunRow)]
    assert counts == [1, 1, 2, 1]


# ---- builds -----------------------------------------------------------------------------


def test_the_same_inputs_return_the_existing_build(session: Session) -> None:
    _pool(session)
    first = _build(session)
    again = _build(session, decks=5)
    assert again.id == first.id and _count(session, BuildRow) == 1
    decks = repository.decks_of(session, first.id)
    assert [d.deck_index for d in decks] == [0, 1] and decks[1].payload == {"label": "deck 1"}


def test_a_build_for_an_unknown_pool_fails_after_exactly_one_reread(session: Session) -> None:
    with pytest.raises(IntegrityError):
        _build(session, pool_id="missing")
    assert _count(session, BuildRow) == 0


def test_a_build_stored_concurrently_is_returned(
    session: Session, sessions: sessionmaker[Session]
) -> None:
    _pool(session)
    _race(
        session,
        sessions,
        lambda other: other.add(
            BuildRow(
                pool_id=POOL,
                inputs_key="k1",
                config_version="0.3",
                mode="event",
                data_lines=["theirs"],
                refusal=None,
                created_at=NOW,
            )
        ),
    )
    build = _build(session)
    assert build.data_lines == ["theirs"] and _count(session, BuildRow) == 1


def test_the_latest_build_is_the_newest_and_scoped_to_the_owner(session: Session) -> None:
    _pool(session)
    assert repository.latest_build(session, "alice", POOL) is None
    _build(session, key="k1")
    second = _build(session, key="k2")
    latest = repository.latest_build(session, "alice", POOL)
    assert latest is not None and latest.id == second.id
    with pytest.raises(repository.NotFound):
        repository.latest_build(session, "bob", POOL)


# ---- runs -------------------------------------------------------------------------------


def test_a_replayed_run_is_returned_and_never_undoes_a_later_edit(session: Session) -> None:
    _pool(session)
    build = _build(session)
    row, created = _run(session, build.id)
    assert created and (row.wins, row.losses) == (3, 1)
    repository.update_run(session, "alice", RUN, LATER, wins=4)
    replay, created_again = _run(session, build.id)
    assert not created_again and (replay.wins, replay.losses) == (4, 1)
    assert _count(session, DeckRunRow) == 1


@pytest.mark.parametrize(("user", "body"), [("alice", "r2"), ("bob", "r1")])
def test_a_run_id_reused_with_another_body_or_user_is_a_conflict(
    session: Session, user: str, body: str
) -> None:
    _pool(session)
    build = _build(session)
    _run(session, build.id)
    with pytest.raises(repository.Conflict):
        _run(session, build.id, user=user, body=body)
    assert session.get(DeckRunRow, RUN).body_hash == "r1"  # type: ignore[union-attr]


@pytest.mark.parametrize(
    ("user", "build_offset", "index"), [("bob", 0, 0), ("alice", 99, 0), ("alice", 0, 7)]
)
def test_a_run_on_a_deck_the_user_does_not_own_is_not_found(
    session: Session, user: str, build_offset: int, index: int
) -> None:
    _pool(session)
    build = _build(session)
    with pytest.raises(repository.NotFound):
        repository.create_run(
            session, user, RUN, build.id + build_offset, index, 1, 1, "", "", "r", NOW
        )


def test_a_run_created_concurrently_with_the_same_body_is_returned(
    session: Session, sessions: sessionmaker[Session]
) -> None:
    _pool(session)
    build = _build(session)

    def theirs(other: Session) -> None:
        other.add(
            DeckRunRow(
                id=RUN,
                user_id="alice",
                build_id=build.id,
                deck_index=0,
                wins=3,
                losses=1,
                event_name="Direct",
                notes="",
                extra={},
                body_hash="r1",
                created_at=NOW,
                updated_at=NOW,
            )
        )

    _race(session, sessions, theirs)
    row, created = _run(session, build.id)
    assert not created and row.id == RUN and _count(session, DeckRunRow) == 1


def test_a_run_that_still_conflicts_on_the_reread_raises(
    session: Session, sessions: sessionmaker[Session]
) -> None:
    _pool(session)
    build = _build(session)

    def theirs(other: Session) -> None:
        other.add(
            DeckRunRow(
                id=RUN,
                user_id="alice",
                build_id=build.id,
                deck_index=0,
                wins=3,
                losses=1,
                event_name="",
                notes="",
                extra={},
                body_hash="r1",
                created_at=NOW,
                updated_at=NOW,
            )
        )

    _race(session, sessions, theirs)
    with pytest.raises(IntegrityError):
        _run(session, build.id, retry=False)


def test_runs_are_listed_newest_first_updated_only_on_change_and_deleted(
    session: Session,
) -> None:
    _pool(session)
    build = _build(session)
    _run(session, build.id)
    later_id = "55555555-5555-5555-5555-555555555555"
    repository.create_run(session, "alice", later_id, build.id, 1, 0, 0, "", "", "x", LATER)
    assert [r.id for r in repository.list_runs(session, "alice")] == [later_id, RUN]
    assert repository.list_runs(session, "bob") == []
    unchanged = repository.update_run(session, "alice", RUN, LATER, wins=3, notes=None)
    assert unchanged.updated_at == NOW
    edited = repository.update_run(
        session, "alice", RUN, LATER, losses=2, event_name="Other", notes="n"
    )
    assert (edited.losses, edited.event_name, edited.notes, edited.updated_at) == (
        2,
        "Other",
        "n",
        LATER,
    )
    with pytest.raises(repository.NotFound):
        repository.get_run(session, "bob", RUN)
    with pytest.raises(repository.NotFound):
        repository.delete_run(session, "bob", RUN)
    repository.delete_run(session, "alice", RUN)
    assert _count(session, DeckRunRow) == 1


# ---- pastes -----------------------------------------------------------------------------

CARD_KEY = PasteKey("FRA", "card-data", EventType.ARENA_DIRECT_SEALED, "17lands-card-data", DAY)
GRADE_KEY = PasteKey("FRA", "grades", None, "llu-marc", DAY)


def _card_paste(sha: str = "a" * 64, **kw: Any) -> StoredPaste:
    return StoredPaste(
        key=kw.pop("key", CARD_KEY),
        label="17Lands card data",
        url=None,
        copied_on=DAY,
        published_on=None,
        columns=("Name", "# GIH", "GIH WR"),
        text_sha256=sha,
        parser_version=1,
        card_rows=(
            CardDataRow("Made-up Knight", "W", "C", 120, 0.575, 80, 0.5),
            CardDataRow("Made-up Relic", "", "U", None, None, None, None),
        ),
    )


def _grade_paste() -> StoredPaste:
    return StoredPaste(
        key=GRADE_KEY,
        label="Marc Anderson, Limited Level-Ups",
        url="https://example.com/list",
        copied_on=DAY,
        published_on=dt.date(2026, 9, 25),
        columns=("Tier",),
        text_sha256="b" * 64,
        parser_version=1,
        grade_rows=(GradeRow("Made-up Knight", "B+", 9.0), GradeRow("Made-up Relic", "TBD", None)),
    )


def test_pastes_round_trip_through_the_database(session: Session) -> None:
    card, grade = _card_paste(), _grade_paste()
    assert repository.save_paste(session, card, "alice", NOW, None)
    assert repository.save_paste(session, grade, "bob", NOW, None)
    rows = repository.list_paste_rows(session, "FRA")
    assert [r.dataset for r in rows] == ["card-data", "grades"]
    assert [repository.to_stored(r) for r in rows] == [card, grade]
    assert repository.stored_pastes(session, "FRA") == ([card, grade], [])
    assert rows[1].event_type == "grades" and rows[1].pasted_by == "bob"
    assert repository.list_paste_rows(session, "SOS") == []


def test_a_paste_from_an_older_parser_is_left_out_and_named(session: Session) -> None:
    old = dataclasses.replace(_card_paste(), parser_version=0)
    repository.save_paste(session, old, "alice", NOW, None)
    repository.save_paste(session, _grade_paste(), "alice", NOW, None)
    pastes, problems = repository.stored_pastes(session, "FRA")
    assert pastes == [_grade_paste()]
    assert problems == [
        f"17Lands card data from {DAY} was stored by an older version; paste it again"
    ]


def test_an_identical_paste_changes_nothing(session: Session) -> None:
    repository.save_paste(session, _card_paste(), "alice", NOW, None)
    assert not repository.save_paste(session, _card_paste(), "bob", LATER, "a" * 64)
    assert not repository.save_paste(session, _card_paste(), "bob", LATER, None)
    row = repository.list_paste_rows(session, "FRA")[0]
    assert (row.pasted_by, row.pasted_at, row.replaced_at) == ("alice", NOW, None)


def test_a_changed_paste_the_same_day_replaces_the_row(session: Session) -> None:
    repository.save_paste(session, _card_paste(), "alice", NOW, None)
    assert repository.save_paste(session, _card_paste(sha="c" * 64), "bob", LATER, "a" * 64)
    rows = repository.list_paste_rows(session, "FRA")
    assert len(rows) == 1
    assert (rows[0].text_sha256, rows[0].pasted_by, rows[0].replaced_at) == (
        "c" * 64,
        "bob",
        LATER,
    )
    assert rows[0].pasted_at == NOW


def test_replacing_a_paste_someone_else_changed_since_the_check_is_a_conflict(
    session: Session,
) -> None:
    repository.save_paste(session, _card_paste(), "alice", NOW, None)
    with pytest.raises(repository.Conflict, match="someone else just pasted"):
        repository.save_paste(session, _card_paste(sha="c" * 64), "bob", LATER, "e" * 64)
    with pytest.raises(repository.Conflict):
        repository.save_paste(session, _card_paste(sha="c" * 64), "bob", LATER, None)
    assert repository.list_paste_rows(session, "FRA")[0].text_sha256 == "a" * 64


def test_the_next_day_is_a_second_paste(session: Session) -> None:
    repository.save_paste(session, _card_paste(), "alice", NOW, None)
    next_day = dataclasses.replace(CARD_KEY, import_day=DAY + dt.timedelta(days=1))
    repository.save_paste(session, _card_paste(key=next_day), "alice", NOW, None)
    assert _count(session, PasteRow) == 2


def test_a_paste_by_an_unknown_user_fails_after_exactly_one_reread(session: Session) -> None:
    with pytest.raises(IntegrityError) as raised:
        repository.save_paste(session, _card_paste(), "nobody", NOW, None)
    assert _count(session, PasteRow) == 0
    assert "Made-up Knight" not in str(raised.value)
    assert "hidden due to hide_parameters" in str(raised.value)


def test_a_paste_that_lost_a_race_is_a_conflict_and_the_winner_stays(
    session: Session, sessions: sessionmaker[Session]
) -> None:
    _race(
        session,
        sessions,
        lambda other: repository.save_paste(other, _card_paste(sha="d" * 64), "bob", NOW, None),
    )
    with pytest.raises(repository.Conflict):
        repository.save_paste(session, _card_paste(), "alice", LATER, None)
    rows = repository.list_paste_rows(session, "FRA")
    assert len(rows) == 1 and (rows[0].text_sha256, rows[0].pasted_by) == ("d" * 64, "bob")


def test_a_paste_that_raced_an_identical_one_changes_nothing(
    session: Session, sessions: sessionmaker[Session]
) -> None:
    _race(
        session,
        sessions,
        lambda other: repository.save_paste(other, _card_paste(), "bob", NOW, None),
    )
    assert not repository.save_paste(session, _card_paste(), "alice", LATER, None)


def _race_before_update(
    session: Session, sessions: sessionmaker[Session], write: Callable[[Session], object]
) -> None:
    """Just before `session` runs its next UPDATE, another session commits `write`: a friend
    whose paste landed between our read and our write."""

    fired: list[bool] = []

    def before_update(state: ORMExecuteState) -> None:
        if state.is_update and not fired:
            fired.append(True)
            with sessions() as other:
                write(other)
                other.commit()

    event.listen(session, "do_orm_execute", before_update)


def test_a_replace_that_lost_a_race_is_a_conflict_and_the_winner_stays(
    session: Session, sessions: sessionmaker[Session]
) -> None:
    repository.save_paste(session, _card_paste(), "alice", NOW, None)
    _race_before_update(
        session,
        sessions,
        lambda other: repository.save_paste(other, _card_paste(sha="d" * 64), "bob", NOW, "a" * 64),
    )
    with pytest.raises(repository.Conflict):
        repository.save_paste(session, _card_paste(sha="c" * 64), "alice", LATER, "a" * 64)
    session.expire_all()
    (row,) = repository.list_paste_rows(session, "FRA")
    assert (row.text_sha256, row.pasted_by, row.replaced_at) == ("d" * 64, "bob", NOW)


def test_a_paste_deleted_since_the_check_is_a_conflict_and_nothing_is_stored(
    session: Session,
) -> None:
    repository.save_paste(session, _card_paste(), "alice", NOW, None)
    assert repository.delete_paste_row(session, CARD_KEY, "alice", False, NOW)
    with pytest.raises(repository.Conflict):
        repository.save_paste(session, _card_paste(sha="c" * 64), "alice", LATER, "a" * 64)
    assert _count(session, PasteRow) == 0


def test_the_same_text_with_a_new_link_or_copy_day_is_an_update(session: Session) -> None:
    repository.save_paste(session, _card_paste(), "alice", NOW, None)
    relinked = dataclasses.replace(_card_paste(), url="https://example.com/new")
    assert repository.save_paste(session, relinked, "bob", LATER, "a" * 64)
    recopied = dataclasses.replace(relinked, copied_on=DAY - dt.timedelta(days=1))
    assert repository.save_paste(session, recopied, "bob", LATER, "a" * 64)
    session.expire_all()
    (row,) = repository.list_paste_rows(session, "FRA")
    assert (row.url, row.copied_on, row.pasted_by) == (
        "https://example.com/new",
        DAY - dt.timedelta(days=1),
        "bob",
    )


def test_the_stored_hash_is_read_whatever_parser_stored_it(session: Session) -> None:
    assert repository.stored_sha(session, CARD_KEY) is None
    repository.save_paste(
        session, dataclasses.replace(_card_paste(), parser_version=0), "alice", NOW, None
    )
    assert repository.stored_sha(session, CARD_KEY) == "a" * 64


def test_deleting_a_paste_removes_only_that_key_and_logs_who(session: Session) -> None:
    repository.save_paste(session, _card_paste(), "alice", NOW, None)
    repository.save_paste(session, _grade_paste(), "bob", NOW, None)
    assert repository.delete_paste_row(session, GRADE_KEY, "bob", False, LATER)
    assert not repository.delete_paste_row(session, GRADE_KEY, "bob", False, LATER)
    assert [r.dataset for r in repository.list_paste_rows(session, "FRA")] == ["card-data"]
    (logged,) = session.scalars(select(PasteDeletion)).all()
    assert (logged.dataset, logged.event_type, logged.source_id, logged.import_day) == (
        "grades",
        "grades",
        "llu-marc",
        DAY,
    )
    assert (logged.pasted_by, logged.deleted_by, logged.deleted_at) == ("bob", "bob", LATER)


def test_only_whoever_pasted_or_the_owner_may_delete_a_paste(session: Session) -> None:
    repository.save_paste(session, _card_paste(), "alice", NOW, None)
    with pytest.raises(repository.Forbidden):
        repository.delete_paste_row(session, CARD_KEY, "bob", False, LATER)
    assert _count(session, PasteRow) == 1 and _count(session, PasteDeletion) == 0
    assert repository.delete_paste_row(session, CARD_KEY, "bob", True, LATER)


def test_an_adjustment_is_logged_once_per_change_and_names_who_made_it(session: Session) -> None:
    def log() -> list[tuple[str, str]]:
        rows = session.scalars(select(CardAdjustmentLog).order_by(CardAdjustmentLog.id))
        return [(r.action, r.changed_by) for r in rows]

    assert repository.set_adjustment(session, "FRA", "A", "add", None, "", "alice", NOW)
    assert not repository.set_adjustment(session, "FRA", "A", "add", None, "", "bob", LATER)
    assert repository.set_adjustment(session, "FRA", "A", None, 1.5, "late game", "bob", LATER)
    (stored,) = repository.list_adjustments(session, "FRA")
    assert (stored.bomb, stored.q_delta, stored.note, stored.by) == (None, 1.5, "late game", "Bob")
    assert repository.set_adjustment(session, "FRA", "A", None, 1.5, "early too", "bob", LATER)
    assert repository.list_adjustments(session, "FRA")[0].note == "early too"
    assert repository.list_adjustments(session, "HOB") == []
    assert repository.clear_adjustment(session, "FRA", "A", "alice", LATER)
    assert not repository.clear_adjustment(session, "FRA", "A", "alice", LATER)
    assert repository.list_adjustments(session, "FRA") == []
    assert log() == [("set", "alice"), ("set", "bob"), ("set", "bob"), ("clear", "alice")]


def test_an_adjuster_without_a_display_name_is_named_by_their_email(session: Session) -> None:
    repository.upsert_user(session, "carol", "carol@example.com", "", "", NOW)
    repository.set_adjustment(session, "FRA", "A", "remove", None, "", "carol", NOW)
    assert repository.list_adjustments(session, "FRA")[0].by == "carol"
