from __future__ import annotations

from fastapi.testclient import TestClient

from arena_wizard.main import app, create_app


def test_healthz_answers_ok_without_any_dependency() -> None:
    response = TestClient(create_app()).get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_the_module_exposes_an_app_for_uvicorn() -> None:
    assert TestClient(app).get("/healthz").status_code == 200
