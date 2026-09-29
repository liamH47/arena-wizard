"""Request bodies for the API. Pydantic lives only here, at the boundary (CLAUDE.md)."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated, Any

from pydantic import AfterValidator, BaseModel, Field

MAX_EXPORT_CHARS = 200_000
MAX_PASTE_CHARS = 5_000_000
MAX_ID = 2**31 - 1
"""The largest integer Postgres and SQLite both store in an INTEGER column."""


def storable(text: str) -> str:
    """Refuse text Postgres cannot store: NUL characters, and lone surrogates."""
    if "\x00" in text:
        raise ValueError("the text contains a NUL character")
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError("the text contains characters that are not valid Unicode") from None
    return text


StorableText = Annotated[str, AfterValidator(storable)]


def web_link(url: str | None) -> str | None:
    """A paste's link is a label only; accept http and https links alone."""
    if url is not None and not url.lower().startswith(("http://", "https://")):
        raise ValueError("the link must start with http:// or https://")
    return url


class PoolCreate(BaseModel):
    """A new pool. The client chooses the id so a retried request cannot duplicate it."""

    id: uuid.UUID
    set_code: str = Field(min_length=2, max_length=8)
    format: str = "bo1_sealed"
    export_text: StorableText = Field(max_length=MAX_EXPORT_CHARS)


class PoolUpdate(BaseModel):
    """A pool's corrected export text, from the review screen."""

    export_text: StorableText = Field(max_length=MAX_EXPORT_CHARS)


class RunCreate(BaseModel):
    """A result against a deck, under a client-chosen id."""

    id: uuid.UUID
    build_id: int = Field(ge=1, le=MAX_ID)
    deck_index: int = Field(ge=0, le=MAX_ID)
    wins: int = Field(ge=0, le=20)
    losses: int = Field(ge=0, le=20)
    event_name: StorableText = Field(default="", max_length=255)
    notes: StorableText = Field(default="", max_length=5_000)


class RunUpdate(BaseModel):
    """The fields a recorded run may change; omitted fields stay as they are."""

    wins: int | None = Field(default=None, ge=0, le=20)
    losses: int | None = Field(default=None, ge=0, le=20)
    event_name: StorableText | None = Field(default=None, max_length=255)
    notes: StorableText | None = Field(default=None, max_length=5_000)


class PasteCreate(BaseModel):
    """Data a friend copied or exported by hand (decision 0005)."""

    set_code: str = Field(min_length=2, max_length=8)
    dataset: str
    source_id: str = Field(max_length=64)
    event_type: str | None = None
    copied_on: dt.date | None = None
    published_on: dt.date | None = None
    url: Annotated[StorableText | None, AfterValidator(web_link)] = Field(
        default=None, max_length=2_000
    )
    replace: bool = False
    text: StorableText = Field(max_length=MAX_PASTE_CHARS)


def dump(model: BaseModel) -> dict[str, Any]:
    """A body as plain JSON values, for hashing."""
    return model.model_dump(mode="json")
