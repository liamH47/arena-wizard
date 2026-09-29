"""The FastAPI application factory.

Every outside dependency is a parameter, so tests build the real app with SQLite, a
recording token exchanger, and a fixed clock (docs/plan.md section 10). Production starts
through `python -m arena_wizard.entrypoint`, which waits for the database and migrates
before `serve` builds the app; never point uvicorn at this module directly.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import DataError, IntegrityError, OperationalError
from sqlalchemy.orm import Session, sessionmaker
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from arena_wizard import __version__
from arena_wizard.api import health, pastes, pools, runs, sets
from arena_wizard.auth import google
from arena_wizard.auth import routes as auth_routes
from arena_wizard.auth.routes import LOCAL_USER, Delisted, delisted_response
from arena_wizard.auth.session import SessionUser
from arena_wizard.config import Settings
from arena_wizard.db import repository
from arena_wizard.db.session import make_engine, session_factory

TokenExchanger = Callable[[str, float], SessionUser]
RETRY_AFTER_SECONDS = 5
LOG = logging.getLogger("arena_wizard")


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


PERMANENT_SQLSTATE_CLASSES = ("28", "3D", "53")
"""Bad credentials, a missing database, and exhausted resources (disk, quota,
connections): retrying will not help, so these answer "database error", not "warming"."""
MAX_BODY_BYTES = 6_000_000
"""Above the largest paste (5 MB); larger bodies are refused before anything reads them."""


def default_exchanger(
    settings: Settings, transport: httpx.BaseTransport | None = None
) -> TokenExchanger:
    """The real Google code exchange for these settings; `transport` is the test seam."""

    def exchange(code: str, at: float) -> SessionUser:
        return google.exchange_code(
            code,
            client_id=settings.google_client_id or "",
            client_secret=settings.google_client_secret or "",
            redirect_uri=settings.redirect_uri,
            now=at,
            transport=transport,
        )

    return exchange


def warming_response(request: Request, exc: Exception) -> Response:
    """503 while the database wakes, or 500 when retrying cannot help.

    One log line names the error class and SQLSTATE, never the statement's parameters,
    and /readyz shows the last one, so the owner can tell sleep from breakage.
    """
    original = getattr(exc, "orig", None)
    sqlstate = getattr(original, "sqlstate", None)
    message = str(original if original is not None else exc).splitlines()[0][:200]
    request.app.state.last_db_error = {
        "at": request.app.state.now().isoformat(),
        "type": type(original).__name__,
        "sqlstate": sqlstate,
        "message": message,
    }
    LOG.warning(
        "database unavailable: %s sqlstate=%s %s", type(original).__name__, sqlstate, message
    )
    if sqlstate and sqlstate[:2] in PERMANENT_SQLSTATE_CLASSES:
        return JSONResponse({"status": "database_error"}, status_code=500)
    return JSONResponse(
        {"status": "warming"},
        status_code=503,
        headers={"Retry-After": str(RETRY_AFTER_SECONDS)},
    )


def validation_response(request: Request, exc: Exception) -> Response:
    """422 naming each invalid field, without echoing the input back.

    FastAPI's default handler returns each error's input, which fails to encode when the
    input holds a lone surrogate (a 500), and would repeat pasted text in the response.
    """
    errors = cast(RequestValidationError, exc).errors()
    detail = [{k: v for k, v in e.items() if k not in ("input", "ctx", "url")} for e in errors]
    return JSONResponse({"detail": jsonable_encoder(detail)}, status_code=422)


def data_error_response(request: Request, exc: Exception) -> Response:
    """A value the database refuses (Postgres rejects NUL characters): 422, no echo."""
    return JSONResponse({"detail": "a value in the request cannot be stored"}, status_code=422)


def conflict_response(request: Request, exc: Exception) -> Response:
    """A write that still conflicts after its one retry: 409, never a 500 with the rows."""
    return JSONResponse(
        {"detail": "that conflicts with stored data; reload, and sign in again if it persists"},
        status_code=409,
    )


class BodyLimit:
    """Refuse request bodies over the limit before the app buffers them (413).

    FastAPI reads and parses a body before running the sign-in check, so without this an
    unauthenticated upload could exhaust a 512 MB instance. A streamed body that passes
    the limit is cut off, and whatever the app then tries to send is replaced with the 413.
    """

    def __init__(self, app: ASGIApp, limit: int = MAX_BODY_BYTES) -> None:
        """Wrap an ASGI app."""
        self.app = app
        self.limit = limit

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Check the declared length, then count the bytes actually received."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        too_large = JSONResponse({"detail": "request too large"}, status_code=413)
        declared = dict(scope.get("headers", [])).get(b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > self.limit:
            await too_large(scope, receive, send)
            return
        seen = 0
        tripped = False

        async def counted() -> Message:
            nonlocal seen, tripped
            message = await receive()
            seen += len(message.get("body", b""))
            if seen > self.limit:
                tripped = True
                raise TooLarge
            return message

        async def guarded(message: Message) -> None:
            if not tripped:
                await send(message)

        with contextlib.suppress(TooLarge):
            await self.app(scope, counted, guarded)
        if tripped:
            await too_large(scope, receive, send)


class TooLarge(Exception):
    """A streamed body passed the limit."""


def _serve_frontend(app: FastAPI, static_dir: Path) -> None:
    """Serve the built frontend after every API route, deep links included."""
    assets = static_dir / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")
    root = static_dir.resolve()

    @app.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    def spa(path: str) -> FileResponse:
        """A real file wins; any other path is the app shell. The shell is never cached,
        so a deploy reaches every phone on its next load."""
        candidate = (static_dir / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(root):
            if candidate.name == "index.html":
                return FileResponse(candidate, headers={"Cache-Control": "no-cache"})
            return FileResponse(candidate)
        index = static_dir / "index.html"
        if not index.is_file():
            raise HTTPException(404, "frontend not built")
        return FileResponse(index, headers={"Cache-Control": "no-cache"})


def create_app(
    settings: Settings,
    *,
    sessions: sessionmaker[Session],
    token_exchanger: TokenExchanger | None = None,
    now: Callable[[], dt.datetime] = _utc_now,
    max_body_bytes: int = MAX_BODY_BYTES,
) -> FastAPI:
    """Build the application.

    Args:
        settings: Validated configuration.
        sessions: Opens database sessions.
        token_exchanger: Trades a Google code for an identity; defaults to the real one.
        now: The clock, aware UTC.
        max_body_bytes: Larger request bodies are refused with 413.

    Returns:
        The app with every route registered.
    """
    app = FastAPI(title="Arena Wizard", version=__version__)
    app.state.settings = settings
    app.state.sessions = sessions
    app.state.now = now
    app.state.boot_at = now()
    app.state.last_db_error = None
    app.state.token_exchanger = token_exchanger or default_exchanger(settings)
    handlers: dict[Any, Any] = {
        OperationalError: warming_response,
        IntegrityError: conflict_response,
        DataError: data_error_response,
        RequestValidationError: validation_response,
        Delisted: delisted_response,
    }
    for exception, handler in handlers.items():
        app.add_exception_handler(exception, handler)
    for module in (health, auth_routes, sets, pools, runs, pastes):
        app.include_router(module.router)

    @app.api_route(
        "/api/{path:path}",
        methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"],
        include_in_schema=False,
    )
    @app.api_route(
        "/api",
        methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"],
        include_in_schema=False,
    )
    def unknown_api(path: str = "") -> None:
        """Unknown API paths are JSON 404s, never the app shell."""
        raise HTTPException(404, f"no API route /api/{path}")

    if settings.static_dir is not None:
        _serve_frontend(app, settings.static_dir)
    app.add_middleware(BodyLimit, limit=max_body_bytes)
    return app


def ensure_local_user(sessions: sessionmaker[Session], now: dt.datetime) -> None:
    """With auth off, every request is the local user, who must exist for foreign keys."""
    with sessions() as session:
        repository.upsert_user(session, LOCAL_USER.user_id, LOCAL_USER.email, "Local", "", now)


def production_app() -> FastAPI:
    """The app uvicorn serves: settings from the environment, the real database."""
    settings = Settings()
    sessions = session_factory(make_engine(settings.database_url))
    if settings.auth == "off":
        ensure_local_user(sessions, _utc_now())
    return create_app(settings, sessions=sessions)


def serve(
    port: int,
    factory: Callable[[], FastAPI] = production_app,
    runner: Callable[..., None] = uvicorn.run,
) -> None:
    """Serve the app on the given port; the entrypoint calls this after migrating."""
    runner(factory(), host="0.0.0.0", port=port, proxy_headers=True)
