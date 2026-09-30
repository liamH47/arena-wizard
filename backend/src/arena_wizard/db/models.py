"""Database tables for the web app (docs/plan.md section 5, docs/schema.md).

Portable SQLAlchemy 2 types, so the same models run on SQLite in tests and Postgres in
production. Every timestamp is stored and returned in UTC, and every foreign key says
what a delete does: a pool takes its builds and decks with it, but a recorded run
protects its deck, so deleting a pool someone played is refused, never silent.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
)
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class UTCDateTime(TypeDecorator[dt.datetime]):
    """A timestamp that is always UTC-aware on the way out; SQLite would return it naive."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: dt.datetime | None, dialect: Dialect) -> dt.datetime | None:
        """Refuse naive timestamps, and store every aware one as UTC."""
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime; pass an aware UTC timestamp")
        return value.astimezone(dt.UTC)

    def process_result_value(
        self, value: dt.datetime | None, dialect: Dialect
    ) -> dt.datetime | None:
        """Attach UTC to whatever the driver returns."""
        if value is None:
            return None
        return value.replace(tzinfo=dt.UTC) if value.tzinfo is None else value.astimezone(dt.UTC)


class Base(DeclarativeBase):
    """The declarative base, with constraint names every migration can refer to."""

    metadata = MetaData(naming_convention=NAMING)
    type_annotation_map = {dict[str, Any]: JSON, list[Any]: JSON}


class User(Base):
    """A signed-in friend, keyed by Google's stable subject id."""

    __tablename__ = "users"

    user_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    email: Mapped[str] = mapped_column(String(320))
    name: Mapped[str] = mapped_column(String(255), default="")
    picture: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[dt.datetime] = mapped_column(UTCDateTime)
    last_seen_at: Mapped[dt.datetime] = mapped_column(UTCDateTime)


class PoolRow(Base):
    """A pasted sealed pool, owned by one user. The id is the client's UUID."""

    __tablename__ = "pools"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.user_id", ondelete="RESTRICT"), index=True
    )
    set_code: Mapped[str] = mapped_column(String(8))
    format: Mapped[str] = mapped_column(String(32))
    raw_text: Mapped[str] = mapped_column(Text)
    body_hash: Mapped[str] = mapped_column(String(64))
    """Hash of what the client sent, so a replayed create is recognised."""
    pool_hash: Mapped[str] = mapped_column(String(64))
    """Hash of the resolved pool, part of every build's inputs key."""
    created_at: Mapped[dt.datetime] = mapped_column(UTCDateTime)
    updated_at: Mapped[dt.datetime] = mapped_column(UTCDateTime)


class BuildRow(Base):
    """One run of the builder on a pool, reused while its inputs are unchanged."""

    __tablename__ = "builds"
    __table_args__ = (UniqueConstraint("pool_id", "inputs_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pool_id: Mapped[str] = mapped_column(ForeignKey("pools.id", ondelete="CASCADE"))
    inputs_key: Mapped[str] = mapped_column(String(64))
    config_version: Mapped[str] = mapped_column(String(32))
    mode: Mapped[str] = mapped_column(String(16))
    """"data" with the public Sealed file, "event" without it (decision 0007)."""
    data_lines: Mapped[list[Any]] = mapped_column()
    """The Data block: what the build used and what was missing."""
    refusal: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(UTCDateTime)


class DeckRow(Base):
    """One ranked deck of a build, with everything the deck page shows."""

    __tablename__ = "decks"

    build_id: Mapped[int] = mapped_column(
        ForeignKey("builds.id", ondelete="CASCADE"), primary_key=True
    )
    deck_index: Mapped[int] = mapped_column(Integer, primary_key=True)
    colors: Mapped[str] = mapped_column(String(8))
    splash: Mapped[str | None] = mapped_column(String(1), nullable=True)
    total: Mapped[float] = mapped_column(Float)
    total_se: Mapped[float] = mapped_column(Float)
    payload: Mapped[dict[str, Any]] = mapped_column()


class DeckRunRow(Base):
    """A result recorded against a deck. Protects its deck from deletion."""

    __tablename__ = "deck_runs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["build_id", "deck_index"],
            ["decks.build_id", "decks.deck_index"],
            ondelete="RESTRICT",
        ),
        Index("ix_deck_runs_deck", "build_id", "deck_index"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.user_id", ondelete="RESTRICT"), index=True
    )
    build_id: Mapped[int] = mapped_column(Integer)
    deck_index: Mapped[int] = mapped_column(Integer)
    wins: Mapped[int] = mapped_column(Integer)
    losses: Mapped[int] = mapped_column(Integer)
    event_name: Mapped[str] = mapped_column(String(255), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    extra: Mapped[dict[str, Any]] = mapped_column(default=dict)
    """Room for later fields (opponent colors, edits between runs) without a migration."""
    body_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[dt.datetime] = mapped_column(UTCDateTime)
    updated_at: Mapped[dt.datetime] = mapped_column(UTCDateTime)


class PasteRow(Base):
    """Data a friend pasted by hand (decisions 0005 and 0007), private to the group.

    The unique key is decision 0005's "one paste per source, set, dataset, and UTC day",
    with the event type. `event_type` is "grades" for grade lists, so the key never holds
    a NULL, which would defeat the constraint. Rows are one JSON column, so a same-day
    replace is one row update.
    """

    __tablename__ = "pastes"
    __table_args__ = (
        UniqueConstraint("set_code", "dataset", "event_type", "source_id", "import_day"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    set_code: Mapped[str] = mapped_column(String(8))
    dataset: Mapped[str] = mapped_column(String(16))
    event_type: Mapped[str] = mapped_column(String(32))
    source_id: Mapped[str] = mapped_column(String(64))
    import_day: Mapped[dt.date] = mapped_column(Date)
    label: Mapped[str] = mapped_column(String(255))
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    copied_on: Mapped[dt.date] = mapped_column(Date)
    published_on: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    columns: Mapped[list[Any]] = mapped_column()
    rows: Mapped[list[Any]] = mapped_column()
    text_sha256: Mapped[str] = mapped_column(String(64))
    parser_version: Mapped[int] = mapped_column(Integer)
    pasted_by: Mapped[str] = mapped_column(ForeignKey("users.user_id", ondelete="RESTRICT"))
    pasted_at: Mapped[dt.datetime] = mapped_column(UTCDateTime)
    replaced_at: Mapped[dt.datetime | None] = mapped_column(UTCDateTime, nullable=True)


class PasteDeletion(Base):
    """Who retracted which paste, and when; never the pasted data itself (decision 0008).

    Kept apart from `pastes` so a deletion does not block that day's key.
    """

    __tablename__ = "paste_deletions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    set_code: Mapped[str] = mapped_column(String(8))
    dataset: Mapped[str] = mapped_column(String(16))
    event_type: Mapped[str] = mapped_column(String(32))
    source_id: Mapped[str] = mapped_column(String(64))
    import_day: Mapped[dt.date] = mapped_column(Date)
    pasted_by: Mapped[str] = mapped_column(String(255))
    deleted_by: Mapped[str] = mapped_column(ForeignKey("users.user_id", ondelete="RESTRICT"))
    deleted_at: Mapped[dt.datetime] = mapped_column(UTCDateTime)


class CardAdjustmentRow(Base):
    """The group's current adjustment to one card (decision 0011)."""

    __tablename__ = "card_adjustments"
    __table_args__ = (UniqueConstraint("set_code", "name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    set_code: Mapped[str] = mapped_column(String(8))
    name: Mapped[str] = mapped_column(String(255))
    bomb: Mapped[str | None] = mapped_column(String(8), nullable=True)
    q_delta: Mapped[float | None] = mapped_column(Float, nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")
    updated_by: Mapped[str] = mapped_column(ForeignKey("users.user_id", ondelete="RESTRICT"))
    updated_at: Mapped[dt.datetime] = mapped_column(UTCDateTime)


class CardAdjustmentLog(Base):
    """Every set or clear of an adjustment, append-only, so edits stay attributable."""

    __tablename__ = "card_adjustment_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    set_code: Mapped[str] = mapped_column(String(8))
    name: Mapped[str] = mapped_column(String(255))
    action: Mapped[str] = mapped_column(String(8))
    bomb: Mapped[str | None] = mapped_column(String(8), nullable=True)
    q_delta: Mapped[float | None] = mapped_column(Float, nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")
    changed_by: Mapped[str] = mapped_column(ForeignKey("users.user_id", ondelete="RESTRICT"))
    changed_at: Mapped[dt.datetime] = mapped_column(UTCDateTime)
