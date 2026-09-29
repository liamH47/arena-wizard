"""Runtime configuration for the web app: the only place environment variables are read.

Ported from draft-kit with the prefix `ARENA_WIZARD_`. It refuses to boot half-configured
and names exactly what is missing (docs/plan.md section 10).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from arena_wizard.datadir import DATA_DIR_ENV, resolve_data_dir

PREFIX = "ARENA_WIZARD_"


def _default_database_url() -> str:
    """SQLite in the private data directory, which is refused inside a git work tree."""
    data = resolve_data_dir(os.environ.get(DATA_DIR_ENV), Path.home())
    return f"sqlite:///{(data / 'web.db').as_posix()}"


class Settings(BaseSettings):
    """Every setting the web app reads, validated once at boot."""

    model_config = SettingsConfigDict(
        env_prefix=PREFIX, env_file=".env", extra="ignore", populate_by_name=True
    )

    env: Literal["dev", "prod"] = "dev"
    auth: Literal["off", "google"] = "off"
    google_client_id: str | None = None
    google_client_secret: str | None = None
    secret_key: str | None = None
    """Signs session cookies; any long random string."""
    public_url: str | None = None
    """Where the site lives. The OAuth redirect derives from it, and its scheme decides the
    cookies' Secure flag."""
    allowed_emails: Annotated[list[str], NoDecode] = []
    """Who may sign in, comma-separated. Re-read on every request, so delisting works."""
    owner_email: str | None = None
    """The owner may delete any friend's paste (decision 0008)."""
    database_url: str = Field(default_factory=lambda: _default_database_url())
    """Postgres in production. The local default lives in the private data directory,
    never inside the repository, because the database holds pasted data (decision 0005)."""
    render: bool = Field(default=False, validation_alias="RENDER")
    """Render sets RENDER=true on every service; there the app must run as prod."""
    git_commit: str | None = Field(default=None, validation_alias="RENDER_GIT_COMMIT")
    """The deployed commit, shown by /readyz so a hotfix can be confirmed with one curl."""
    static_dir: Path | None = None
    """The built frontend, served same-origin in production."""

    @field_validator("allowed_emails", mode="before")
    @classmethod
    def _split_emails(cls, value: str | list[str]) -> list[str]:
        """Environment variables arrive as one comma-separated string."""
        items = value.split(",") if isinstance(value, str) else value
        return [item.strip().lower() for item in items if item.strip()]

    @field_validator("owner_email")
    @classmethod
    def _lower_owner(cls, value: str | None) -> str | None:
        return value.lower() if value else value

    @model_validator(mode="after")
    def _complete(self) -> Self:
        """Refuse to boot half-configured, naming every missing variable."""
        missing: list[str] = []
        if self.render and self.env != "prod":
            # Fail closed: a deploy that forgot ARENA_WIZARD_ENV would otherwise serve
            # every pasted number to the internet with auth off (decision 0008).
            missing.append(f"{PREFIX}ENV=prod (this is a Render service)")
        if self.auth == "google":
            required = {
                "GOOGLE_CLIENT_ID": self.google_client_id,
                "GOOGLE_CLIENT_SECRET": self.google_client_secret,
                "SECRET_KEY": self.secret_key,
                "PUBLIC_URL": self.public_url,
                "ALLOWED_EMAILS": ",".join(self.allowed_emails),
                "OWNER_EMAIL": self.owner_email,
            }
            missing += [PREFIX + name for name, value in required.items() if not value]
        if self.env == "prod":
            if self.auth != "google":
                missing.append(f"{PREFIX}AUTH=google")
            if self.database_url.startswith("sqlite"):
                missing.append(f"{PREFIX}DATABASE_URL (a Postgres URL, not SQLite)")
        if missing:
            raise ValueError(f"configuration incomplete; set: {', '.join(missing)}")
        return self

    @property
    def redirect_uri(self) -> str:
        """The OAuth callback; only meaningful in google mode, where public_url is set."""
        return f"{(self.public_url or '').rstrip('/')}/auth/google/callback"

    @property
    def secure_cookies(self) -> bool:
        """Secure cookies only over https; a plain-http localhost run would drop them."""
        return (self.public_url or "").startswith("https://")
