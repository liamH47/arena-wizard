from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from arena_wizard.auth.google import ExchangeError
from arena_wizard.auth.routes import STATE_COOKIE
from arena_wizard.auth.session import COOKIE_NAME, SessionUser, verify_session
from arena_wizard.db.models import User
from tests.api.app_fixture import FIXED, FRIEND, SECRET, make_app, signed_in

STRANGER = SessionUser("sub-stranger", "stranger@example.com", "Stranger")


class Exchanger:
    """Stands in for Google: records each code it is given and answers one way."""

    def __init__(self, answer: SessionUser | Exception) -> None:
        self.answer = answer
        self.calls: list[tuple[str, float]] = []

    def __call__(self, code: str, at: float) -> SessionUser:
        self.calls.append((code, at))
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def _set_cookie_headers(response: httpx.Response) -> list[str]:
    return list(response.headers.get_list("set-cookie"))


def _start(client: TestClient) -> str:
    """Begin sign-in and return the state the login route chose."""
    response = client.get("/auth/google/login", follow_redirects=False)
    return str(parse_qs(urlparse(response.headers["location"]).query)["state"][0])


def test_sign_in_routes_do_not_exist_with_auth_off(tmp_path: Path) -> None:
    _, client, _ = make_app(tmp_path)
    assert client.get("/auth/google/login", follow_redirects=False).status_code == 404
    assert client.get("/auth/google/callback?code=x&state=y").status_code == 404


def test_login_redirects_to_google_with_a_state_cookie(tmp_path: Path) -> None:
    _, client, _ = make_app(tmp_path, auth="google")
    response = client.get("/auth/google/login", follow_redirects=False)
    assert response.status_code == 307
    location = urlparse(response.headers["location"])
    assert location.netloc == "accounts.google.com"
    query = parse_qs(location.query)
    assert query["redirect_uri"] == ["https://testserver/auth/google/callback"]
    (cookie,) = _set_cookie_headers(response)
    assert cookie.startswith(f"{STATE_COOKIE}={query['state'][0]};")
    lowered = cookie.lower()
    assert "path=/auth" in lowered and "httponly" in lowered and "secure" in lowered


def test_the_state_cookie_is_not_secure_over_plain_http(tmp_path: Path) -> None:
    _, client, _ = make_app(tmp_path, auth="google", public_url="http://localhost:5173")
    response = client.get("/auth/google/login", follow_redirects=False)
    assert "secure" not in _set_cookie_headers(response)[0].lower()


def _back_to(client: TestClient, query: str) -> str:
    response = client.get(f"/auth/google/callback?{query}", follow_redirects=False)
    assert response.status_code == 302
    location: str = response.headers["location"]
    return location


def test_a_callback_without_a_matching_state_goes_back_to_login(tmp_path: Path) -> None:
    exchange = Exchanger(FRIEND)
    _, client, _ = make_app(tmp_path, auth="google", exchanger=exchange)
    assert _back_to(client, "code=c&state=s") == "/login?error=state"
    state = _start(client)
    assert _back_to(client, "code=c") == "/login?error=state"
    assert _back_to(client, "code=c&state=wrong") == "/login?error=state"
    state = _start(client)
    assert _back_to(client, "code=c&state=%C3%A9") == "/login?error=state"
    state = _start(client)
    assert _back_to(client, f"state={state}") == "/login?error=cancelled"
    assert exchange.calls == []


def test_cancelling_at_google_goes_back_to_login(tmp_path: Path) -> None:
    exchange = Exchanger(FRIEND)
    _, client, _ = make_app(tmp_path, auth="google", exchanger=exchange)
    state = _start(client)
    assert _back_to(client, f"error=access_denied&state={state}") == "/login?error=cancelled"
    assert exchange.calls == []


def test_a_failed_exchange_goes_back_to_login(tmp_path: Path) -> None:
    _, client, _ = make_app(tmp_path, auth="google", exchanger=Exchanger(ExchangeError("no")))
    state = _start(client)
    assert _back_to(client, f"code=c&state={state}") == "/login?error=google"


def test_a_sleeping_database_during_sign_in_goes_back_to_login(tmp_path: Path) -> None:
    app, client, _ = make_app(tmp_path, auth="google", exchanger=Exchanger(FRIEND))

    class Asleep:
        def __call__(self) -> Any:
            raise OperationalError("SELECT 1", {}, Exception("the database is waking"))

    app.state.sessions = Asleep()
    state = _start(client)
    assert _back_to(client, f"code=c&state={state}") == "/login?error=warming"


def test_a_non_ascii_session_cookie_reads_as_signed_out() -> None:
    assert verify_session(SECRET, "abc.d\u00e9f") is None


def test_an_unlisted_email_is_sent_to_the_denied_page_without_a_session(tmp_path: Path) -> None:
    _, client, sessions = make_app(tmp_path, auth="google", exchanger=Exchanger(STRANGER))
    state = _start(client)
    response = client.get(f"/auth/google/callback?code=c&state={state}", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/login?error=denied"
    headers = _set_cookie_headers(response)
    assert not any(h.startswith(f"{COOKIE_NAME}=") for h in headers)
    assert any(h.startswith(f'{STATE_COOKIE}=""') for h in headers)
    with sessions() as session:
        assert session.get(User, STRANGER.user_id) is None


def test_a_listed_user_signs_in_is_recorded_and_gets_a_session(tmp_path: Path) -> None:
    exchange = Exchanger(FRIEND)
    _, client, sessions = make_app(tmp_path, auth="google", exchanger=exchange)
    state = _start(client)
    response = client.get(f"/auth/google/callback?code=c&state={state}", follow_redirects=False)
    assert response.status_code == 302 and response.headers["location"] == "/"
    headers = _set_cookie_headers(response)
    session_cookie = next(h for h in headers if h.startswith(f"{COOKIE_NAME}="))
    token = session_cookie.split(";")[0].split("=", 1)[1]
    assert verify_session(SECRET, token) == FRIEND
    assert "httponly" in session_cookie.lower() and "secure" in session_cookie.lower()
    assert any(h.startswith(f'{STATE_COOKIE}=""') for h in headers)
    assert exchange.calls[0][0] == "c"
    with sessions() as session:
        user = session.get(User, FRIEND.user_id)
        assert user is not None and user.email == FRIEND.email
        assert user.last_seen_at == FIXED


def test_logout_clears_the_session_cookie(tmp_path: Path) -> None:
    _, client, _ = make_app(tmp_path, auth="google")
    response = client.post("/auth/logout")
    assert response.json() == {"ok": True}
    assert any(h.startswith(f'{COOKIE_NAME}=""') for h in _set_cookie_headers(response))


def test_me_says_auth_is_off_and_names_the_local_user(tmp_path: Path) -> None:
    _, client, _ = make_app(tmp_path)
    body = client.get("/api/me").json()
    assert body["auth"] == "off" and body["user"]["user_id"] == "local"
    assert body["owner"] is True


def test_me_is_always_200_and_names_only_listed_signed_in_users(tmp_path: Path) -> None:
    app, client, _ = make_app(tmp_path, auth="google")
    assert client.get("/api/me").json() == {"auth": "google", "user": None, "owner": False}
    signed_in(client, app.state.settings)
    body = client.get("/api/me").json()
    assert body["user"]["email"] == FRIEND.email and body["owner"] is False
    app.state.settings.allowed_emails.remove(FRIEND.email)
    response = client.get("/api/me")
    assert response.status_code == 200 and response.json()["user"] is None
    assert response.json()["owner"] is False


def test_me_names_the_owner_so_the_pastes_page_can_offer_delete(tmp_path: Path) -> None:
    app, client, _ = make_app(tmp_path, auth="google")
    owner = SessionUser(user_id="sub-owner", email="owner@example.com", name="Owner")
    app.state.settings.allowed_emails.append(owner.email)
    signed_in(client, app.state.settings, owner)
    assert client.get("/api/me").json()["owner"] is True
    app.state.settings.allowed_emails.remove(owner.email)
    assert client.get("/api/me").json()["owner"] is False


def test_api_routes_need_a_session_and_a_delisted_user_is_refused(tmp_path: Path) -> None:
    app, client, _ = make_app(tmp_path, auth="google")
    assert client.get("/api/sets").status_code == 401
    client.cookies.set(COOKIE_NAME, "garbage")
    assert client.get("/api/sets").status_code == 401
    signed_in(client, app.state.settings)
    assert client.get("/api/sets").status_code == 200
    app.state.settings.allowed_emails.remove(FRIEND.email)
    response = client.get("/api/sets")
    assert response.status_code == 403 and response.json() == {"detail": "not on the allow-list"}
    assert any(h.startswith(f'{COOKIE_NAME}=""') for h in _set_cookie_headers(response))


def test_with_auth_off_api_routes_answer_as_the_local_user(tmp_path: Path) -> None:
    _, client, _ = make_app(tmp_path)
    assert client.get("/api/sets").status_code == 200
