"""Shared dependencies: a database session per request, and the clock."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session


def db_session(request: Request) -> Iterator[Session]:
    """One session per request, closed afterwards."""
    with request.app.state.sessions() as session:
        yield session


def clock(request: Request) -> dt.datetime:
    """The injected clock's current aware UTC time."""
    now: dt.datetime = request.app.state.now()
    return now


DbSession = Annotated[Session, Depends(db_session)]
Now = Annotated[dt.datetime, Depends(clock)]
