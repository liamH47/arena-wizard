"""Sign-in with Google, the allow-list, and the identity every API route depends on.

Ported from draft-kit with the plan's amendments: the allow-list is checked on every
request, not only at sign-in, so removing a friend takes effect on their next click; and
a delisted user gets 403 with the cookie cleared, which the frontend turns into the
"ask the owner" page.
"""

from __future__ import annotations

import secrets
import time
from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from sqlalchemy.exc import OperationalError

from arena_wizard.auth.google import ExchangeError, authorize_url
from arena_wizard.auth.session import (
    COOKIE_NAME,
    MAX_AGE_SECONDS,
    SessionUser,
    sign_session,
    verify_session,
)
from arena_wizard.config import Settings
from arena_wizard.db import repository

router = APIRouter()

STATE_COOKIE = "aw_oauth_state"
LOCAL_USER = SessionUser(user_id="local", email="")


class Delisted(Exception):
    """A signed-in user whose email is no longer on the allow-list."""


def _session_user(request: Request) -> SessionUser | None:
    settings: Settings = request.app.state.settings
    token = request.cookies.get(COOKIE_NAME)
    return verify_session(settings.secret_key or "", token) if token else None


def current_user(request: Request) -> SessionUser:
    """Who is asking: the local user with auth off, else the verified, still-listed user.

    Raises:
        HTTPException: 401 without a valid session cookie.
        Delisted: The cookie is valid but the email was removed from the allow-list.
    """
    settings: Settings = request.app.state.settings
    if settings.auth != "google":
        return LOCAL_USER
    user = _session_user(request)
    if user is None:
        raise HTTPException(401, "not signed in")
    if user.email not in settings.allowed_emails:
        raise Delisted(user.email)
    return user


CurrentUser = Annotated[SessionUser, Depends(current_user)]


def delisted_response(request: Request, exc: Exception) -> Response:
    """403 with the session cookie cleared, for a user who was removed from the list."""
    response = JSONResponse({"detail": "not on the allow-list"}, status_code=403)
    response.delete_cookie(COOKIE_NAME, path="/")
    return response


def _require_google(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    if settings.auth != "google":
        raise HTTPException(404, "sign-in is not enabled on this install")
    return settings


@router.get("/auth/google/login")
def login(request: Request) -> RedirectResponse:
    """Start signing in: remember a random state and send the browser to Google."""
    settings = _require_google(request)
    state = secrets.token_urlsafe(16)
    response = RedirectResponse(
        authorize_url(settings.google_client_id or "", settings.redirect_uri, state)
    )
    response.set_cookie(
        STATE_COOKIE,
        state,
        max_age=600,
        httponly=True,
        samesite="lax",
        secure=settings.secure_cookies,
        path="/auth",
    )
    return response


def _back_to_login(reason: str) -> RedirectResponse:
    """The callback is a full-page navigation from Google, so every failure returns to the
    login page with a reason it can explain, never raw JSON."""
    response = RedirectResponse(f"/login?error={reason}", status_code=302)
    response.delete_cookie(STATE_COOKIE, path="/auth")
    return response


@router.get("/auth/google/callback")
def callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    """Finish signing in: check the state, exchange the code, and apply the allow-list."""
    settings = _require_google(request)
    if error is not None:
        return _back_to_login("cancelled")
    expected = request.cookies.get(STATE_COOKIE)
    if (
        not state
        or not expected
        or not secrets.compare_digest(state.encode("utf-8"), expected.encode("utf-8"))
    ):
        return _back_to_login("state")
    if not code:
        return _back_to_login("cancelled")
    try:
        user: SessionUser = request.app.state.token_exchanger(code, time.time())
    except ExchangeError:
        return _back_to_login("google")
    if user.email not in settings.allowed_emails:
        return _back_to_login("denied")
    try:
        with request.app.state.sessions() as session:
            repository.upsert_user(
                session, user.user_id, user.email, user.name, user.picture, request.app.state.now()
            )
    except OperationalError:
        return _back_to_login("warming")
    response = RedirectResponse("/", status_code=302)
    response.set_cookie(
        COOKIE_NAME,
        sign_session(settings.secret_key or "", user),
        max_age=MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
        secure=settings.secure_cookies,
        path="/",
    )
    response.delete_cookie(STATE_COOKIE, path="/auth")
    return response


@router.post("/auth/logout")
def logout() -> JSONResponse:
    """Forget the session cookie."""
    response = JSONResponse({"ok": True})
    response.delete_cookie(COOKIE_NAME, path="/")
    return response


@router.get("/api/me")
def me(request: Request) -> dict[str, Any]:
    """Always 200, so the login page can ask who is signed in without a redirect loop."""
    settings: Settings = request.app.state.settings
    if settings.auth != "google":
        return {"auth": "off", "user": asdict(LOCAL_USER)}
    user = _session_user(request)
    listed = user is not None and user.email in settings.allowed_emails
    return {"auth": "google", "user": asdict(user) if user and listed else None}
