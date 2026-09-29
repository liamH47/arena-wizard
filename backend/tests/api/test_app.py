"""The app factory: unknown API paths, the served frontend, and its injected seams."""

from __future__ import annotations

import base64
import datetime as dt
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from arena_wizard import main
from arena_wizard.auth import google
from arena_wizard.auth.session import SessionUser
from arena_wizard.config import Settings
from arena_wizard.db.models import PasteRow, User
from arena_wizard.db.session import make_engine, session_factory
from arena_wizard.entrypoint import migrate
from arena_wizard.main import create_app, production_app, serve
from tests.api.app_fixture import ALICE, as_user, make


def test_unknown_api_paths_are_json_404s_not_the_app_shell(tmp_path: Path) -> None:
    static = tmp_path / "dist"
    static.mkdir()
    (static / "index.html").write_text("<html>shell</html>", encoding="utf-8")
    _, client, _ = make(tmp_path, static_dir=static)
    for method in ("get", "post", "put", "patch", "delete"):
        response = client.request(method, "/api/no/such/route")
        assert response.status_code == 404
        assert response.json() == {"detail": "no API route /api/no/such/route"}


def _frontend(tmp_path: Path, *, assets: bool = True, index: bool = True) -> Path:
    static = tmp_path / "dist"
    static.mkdir()
    if index:
        (static / "index.html").write_text("<html>shell</html>", encoding="utf-8")
    (static / "favicon.svg").write_text("<svg/>", encoding="utf-8")
    if assets:
        (static / "assets").mkdir()
        (static / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("outside the build", encoding="utf-8")
    return static


def test_deep_links_serve_the_uncached_app_shell_and_real_files_win(tmp_path: Path) -> None:
    _, client, _ = make(tmp_path, static_dir=_frontend(tmp_path))
    for path in ("/", "/pools/abc/decks"):
        shell = client.get(path)
        assert shell.status_code == 200 and shell.text == "<html>shell</html>"
        assert shell.headers["cache-control"] == "no-cache"
    assert client.get("/favicon.svg").text == "<svg/>"
    assert client.get("/assets/app.js").text == "console.log(1)"


def test_a_path_outside_the_build_falls_back_to_the_shell(tmp_path: Path) -> None:
    _, client, _ = make(tmp_path, static_dir=_frontend(tmp_path))
    response = client.get("/%2E%2E/secret.txt")
    assert "outside the build" not in response.text
    assert response.text == "<html>shell</html>"


def test_a_build_without_assets_still_serves_and_a_missing_shell_is_404(tmp_path: Path) -> None:
    _, client, _ = make(tmp_path, static_dir=_frontend(tmp_path, assets=False, index=False))
    assert client.get("/favicon.svg").status_code == 200
    missing = client.get("/pools")
    assert missing.status_code == 404 and missing.json()["detail"] == "frontend not built"


def test_without_a_static_dir_the_app_serves_only_the_api(tmp_path: Path) -> None:
    _, client, _ = make(tmp_path)
    assert client.get("/pools").status_code == 404


def _google_settings() -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        auth="google",
        google_client_id="cid",
        google_client_secret="secret",
        secret_key="k",
        public_url="https://aw.example.com/",
        allowed_emails=["a@example.com"],
        owner_email="a@example.com",
    )


def _token_response(claims: dict[str, Any]) -> httpx.Response:
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    return httpx.Response(200, json={"id_token": f"h.{payload}.s"})


def test_the_default_exchanger_sends_google_the_code_and_this_app_s_redirect() -> None:
    forms: list[dict[str, list[str]]] = []

    def google_token_endpoint(request: httpx.Request) -> httpx.Response:
        forms.append(parse_qs(request.content.decode()))
        return _token_response(
            {
                "aud": "cid",
                "iss": "https://accounts.google.com",
                "exp": 200.0,
                "email_verified": True,
                "sub": "sub-1",
                "email": "A@Example.com",
            }
        )

    exchange = main.default_exchanger(
        _google_settings(), transport=httpx.MockTransport(google_token_endpoint)
    )
    assert exchange("the-code", 100.0) == SessionUser("sub-1", "a@example.com")
    assert forms == [
        {
            "code": ["the-code"],
            "client_id": ["cid"],
            "client_secret": ["secret"],
            "redirect_uri": ["https://aw.example.com/auth/google/callback"],
            "grant_type": ["authorization_code"],
        }
    ]
    with pytest.raises(google.ExchangeError, match="expired"):
        exchange("the-code", 300.0)


def test_the_default_clock_is_aware_utc_now() -> None:
    before = dt.datetime.now(dt.UTC)
    app = create_app(_google_settings(), sessions=session_factory(make_engine("sqlite://")))
    assert app.state.boot_at.tzinfo is dt.UTC
    assert before <= app.state.boot_at <= dt.datetime.now(dt.UTC)
    assert app.state.token_exchanger is not None


def _database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    url = f"sqlite:///{(tmp_path / 'prod.db').as_posix()}"
    migrate(url)
    monkeypatch.setenv("ARENA_WIZARD_DATABASE_URL", url)
    return url


def _users(url: str) -> list[str]:
    with session_factory(make_engine(url))() as session:
        return [u.user_id for u in session.scalars(select(User))]


def test_the_production_app_creates_the_local_user_when_auth_is_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = _database(tmp_path, monkeypatch)
    monkeypatch.setenv("ARENA_WIZARD_AUTH", "off")
    assert isinstance(production_app(), FastAPI)
    assert _users(url) == ["local"]


def test_the_production_app_creates_no_local_user_with_google_auth(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = _database(tmp_path, monkeypatch)
    for name, value in {
        "AUTH": "google",
        "GOOGLE_CLIENT_ID": "cid",
        "GOOGLE_CLIENT_SECRET": "secret",
        "SECRET_KEY": "k",
        "PUBLIC_URL": "https://aw.example.com",
        "ALLOWED_EMAILS": "a@example.com",
        "OWNER_EMAIL": "a@example.com",
    }.items():
        monkeypatch.setenv(f"ARENA_WIZARD_{name}", value)
    assert production_app().state.settings.auth == "google"
    assert _users(url) == []


def test_serve_runs_a_working_app_on_the_given_port(tmp_path: Path) -> None:
    app, _, _ = make(tmp_path)
    served: list[tuple[int, int]] = []

    def runner(served_app: FastAPI, *, port: int, **_: Any) -> None:
        served.append((port, TestClient(served_app).get("/healthz").status_code))

    serve(8123, factory=lambda: app, runner=runner)
    assert served == [(8123, 200)]


def test_the_bare_api_path_is_a_json_404(tmp_path: Path) -> None:
    _, client, _ = make(tmp_path, static_dir=_frontend(tmp_path))
    response = client.get("/api")
    assert response.status_code == 404 and response.json() == {"detail": "no API route /api/"}


def test_the_shell_is_uncached_even_by_its_own_name_and_answers_head(tmp_path: Path) -> None:
    _, client, _ = make(tmp_path, static_dir=_frontend(tmp_path))
    direct = client.get("/index.html")
    assert direct.text == "<html>shell</html>" and direct.headers["cache-control"] == "no-cache"
    assert "cache-control" not in client.get("/favicon.svg").headers
    assert client.head("/pools/abc").status_code == 200


def test_a_declared_oversized_body_is_refused_before_it_is_read(tmp_path: Path) -> None:
    _, client, _ = make(tmp_path)
    response = client.post(
        "/api/pastes",
        content=b"{}",
        headers={
            "content-length": str(main.MAX_BODY_BYTES + 1),
            "content-type": "application/json",
        },
    )
    assert response.status_code == 413 and response.json() == {"detail": "request too large"}


async def _echo(scope: Any, receive: Any, send: Any) -> None:
    body = b""
    while True:
        message = await receive()
        body += message.get("body", b"")
        if not message.get("more_body"):
            break
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": body})


def test_a_streamed_body_is_cut_off_once_it_passes_the_limit() -> None:
    client = TestClient(main.BodyLimit(_echo, limit=10))
    small = client.post("/", content=iter([b"12345", b"67890"]))
    assert small.status_code == 200 and small.content == b"1234567890"
    big = client.post("/", content=iter([b"12345", b"678901"]))
    assert big.status_code == 413


def _chunks(total: int, size: int = 250) -> Iterator[bytes]:
    sent = 0
    while sent < total:
        yield b"x" * min(size, total - sent)
        sent += size


@pytest.mark.parametrize("signed_in", [True, False])
def test_a_streamed_oversized_body_through_a_real_route_is_a_413(
    tmp_path: Path, signed_in: bool
) -> None:
    _, client, sessions = make(tmp_path, max_body_bytes=1000)
    headers = {"content-type": "application/json"} | (as_user(ALICE) if signed_in else {})
    response = client.post("/api/pastes", content=_chunks(2000), headers=headers)
    assert response.status_code == 413 and response.json() == {"detail": "request too large"}
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(PasteRow)) == 0


def test_a_declared_oversized_body_through_a_real_route_is_a_413(tmp_path: Path) -> None:
    _, client, _ = make(tmp_path, max_body_bytes=1000)
    response = client.post(
        "/api/pools", content=b"x" * 1001, headers={"content-type": "application/json"}
    )
    assert response.status_code == 413


def test_a_body_under_the_limit_reaches_the_route(tmp_path: Path) -> None:
    _, client, _ = make(tmp_path, max_body_bytes=1000)
    response = client.post(
        "/api/pastes", content=_chunks(500), headers={"content-type": "application/json"}
    )
    # FastAPI parses the body before the sign-in check, so an invalid body under the limit
    # is the route's own 422, never the limit's 413.
    assert response.status_code == 422


def test_lifespan_events_pass_through_the_body_limit(tmp_path: Path) -> None:
    app, _, _ = make(tmp_path)
    with TestClient(app) as client:
        assert client.get("/healthz").status_code == 200
