from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from arena_wizard.config import Settings

GOOGLE = {
    "auth": "google",
    "google_client_id": "id",
    "google_client_secret": "secret",
    "secret_key": "key",
    "public_url": "https://wizard.example.com/",
    "allowed_emails": "a@example.com",
    "owner_email": "Owner@Example.com",
}


def _settings(**values: Any) -> Settings:
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


def test_the_defaults_are_a_local_install_with_auth_off() -> None:
    settings = _settings()
    assert settings.env == "dev" and settings.auth == "off"
    assert settings.database_url.startswith("sqlite")
    assert settings.allowed_emails == [] and settings.static_dir is None


def test_google_auth_with_nothing_set_names_every_missing_variable() -> None:
    with pytest.raises(ValidationError) as error:
        _settings(auth="google")
    message = str(error.value)
    for name in (
        "GOOGLE_CLIENT_ID",
        "GOOGLE_CLIENT_SECRET",
        "SECRET_KEY",
        "PUBLIC_URL",
        "ALLOWED_EMAILS",
        "OWNER_EMAIL",
    ):
        assert f"ARENA_WIZARD_{name}" in message


@pytest.mark.parametrize(
    ("missing", "variable"),
    [
        ("google_client_id", "GOOGLE_CLIENT_ID"),
        ("google_client_secret", "GOOGLE_CLIENT_SECRET"),
        ("secret_key", "SECRET_KEY"),
        ("public_url", "PUBLIC_URL"),
        ("allowed_emails", "ALLOWED_EMAILS"),
        ("owner_email", "OWNER_EMAIL"),
    ],
)
def test_google_auth_missing_one_variable_names_it(missing: str, variable: str) -> None:
    values = dict(GOOGLE) | {missing: ""}
    with pytest.raises(ValidationError, match=f"ARENA_WIZARD_{variable}"):
        _settings(**values)


def test_on_render_the_app_refuses_to_boot_unless_it_is_production() -> None:
    with pytest.raises(ValidationError, match=r"ARENA_WIZARD_ENV=prod \(this is a Render"):
        _settings(RENDER="true")
    with pytest.raises(ValidationError, match="ARENA_WIZARD_ENV=prod"):
        _settings(render=True, database_url="postgresql+psycopg://u:p@h/db", **GOOGLE)
    settings = _settings(
        RENDER="true",
        RENDER_GIT_COMMIT="abc123",
        env="prod",
        database_url="postgresql+psycopg://u:p@h/db",
        **GOOGLE,
    )
    assert settings.render and settings.git_commit == "abc123"


def test_the_local_database_defaults_to_the_private_data_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ARENA_WIZARD_DATA_DIR", str(tmp_path / "private"))
    url = _settings().database_url
    assert url == f"sqlite:///{(tmp_path / 'private').resolve().as_posix()}/web.db"


def test_complete_google_settings_boot() -> None:
    settings = _settings(**GOOGLE)
    assert settings.owner_email == "owner@example.com"
    assert settings.redirect_uri == "https://wizard.example.com/auth/google/callback"
    assert settings.secure_cookies


def test_production_requires_google_auth_and_postgres() -> None:
    with pytest.raises(ValidationError) as error:
        _settings(env="prod")
    assert "ARENA_WIZARD_AUTH=google" in str(error.value)
    assert "ARENA_WIZARD_DATABASE_URL" in str(error.value)


def test_production_with_google_and_postgres_boots() -> None:
    settings = _settings(env="prod", database_url="postgresql+psycopg://u:p@h/db", **GOOGLE)
    assert settings.env == "prod"


def test_production_on_sqlite_is_refused_even_with_google() -> None:
    with pytest.raises(ValidationError, match="not SQLite"):
        _settings(env="prod", **GOOGLE)


def test_allowed_emails_are_split_trimmed_and_lower_cased() -> None:
    settings = _settings(allowed_emails=" A@Example.com, ,b@example.com ")
    assert settings.allowed_emails == ["a@example.com", "b@example.com"]
    assert _settings(allowed_emails=["C@Example.com"]).allowed_emails == ["c@example.com"]


def test_the_owner_email_is_lower_cased_and_may_be_absent() -> None:
    assert _settings(owner_email="Owner@Example.com").owner_email == "owner@example.com"
    assert _settings().owner_email is None


def test_plain_http_is_not_secure_and_no_public_url_gives_a_bare_path() -> None:
    assert not _settings(public_url="http://localhost:5173").secure_cookies
    settings = _settings()
    assert not settings.secure_cookies
    assert settings.redirect_uri == "/auth/google/callback"


def test_settings_read_the_prefixed_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARENA_WIZARD_ALLOWED_EMAILS", "X@example.com,y@example.com")
    assert _settings().allowed_emails == ["x@example.com", "y@example.com"]
    monkeypatch.delenv("ARENA_WIZARD_ALLOWED_EMAILS")
