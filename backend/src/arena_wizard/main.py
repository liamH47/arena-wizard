"""The FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI

from arena_wizard import __version__


def create_app() -> FastAPI:
    """Build the application.

    Returns:
        The app with its routes registered.
    """
    app = FastAPI(title="Arena Wizard", version=__version__)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        """Liveness: answers without touching any dependency, so it cannot flap."""
        return {"status": "ok"}

    return app


app = create_app()
