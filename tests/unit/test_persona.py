# ruff: noqa: F811  -- pytest injects the imported `billing` fixture by parameter name
"""Persona: saved and validated, kept when a screen doesn't send it, shapes
the system prompt, and decides the plan /billing recommends."""
from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from harness.api.auth import get_current_user
from harness.api.routes import billing as billing_route
from harness.api.routes import settings as settings_route
from harness.db.settings import PERSONAS, Settings, prompt_block, save_settings
from tests.unit.test_billing import _app, billing  # noqa: F401


def _settings_client(monkeypatch, stored):
    monkeypatch.setattr(settings_route, "get_settings", lambda uid: stored[uid])

    def save(uid, values):
        if values.persona and values.persona not in PERSONAS:      # the real validation, without a DB
            raise ValueError("persona must be one of …")
        stored[uid] = values
        return values
    monkeypatch.setattr(settings_route, "save_settings", save)
    app = FastAPI()
    app.include_router(settings_route.router)
    app.dependency_overrides[get_current_user] = lambda: {"user_id": "7"}
    return TestClient(app)


def test_persona_is_saved_kept_and_validated(monkeypatch):
    stored = {"7": Settings(timezone="UTC", persona="student")}
    c = _settings_client(monkeypatch, stored)
    base = {"timezone": "UTC"}
    assert c.put("/settings", json=base).json()["persona"] == "student"            # not sent: kept
    assert c.put("/settings", json={**base, "persona": "founder"}).json()["persona"] == "founder"
    assert c.put("/settings", json={**base, "persona": "astronaut"}).status_code == 422
    assert c.put("/settings", json={**base, "persona": ""}).json()["persona"] == ""   # cleared on purpose


def test_save_settings_refuses_an_unknown_persona():
    import pytest
    with pytest.raises(ValueError):
        save_settings("7", Settings(timezone="UTC", persona="astronaut"))


def test_the_prompt_says_who_they_are():
    now = datetime(2026, 10, 3, 9, tzinfo=UTC)
    block = prompt_block(Settings(timezone="UTC", persona="developer"), now)
    assert "Who they are: Software developer" in block
    assert "Who they are" not in prompt_block(Settings(timezone="UTC"), now)


def test_billing_recommends_a_plan_for_the_persona(billing, monkeypatch):
    for persona, plan in (("founder", "plus"), ("developer", "pro"), ("student", "plus"), ("", None)):
        monkeypatch.setattr("harness.db.settings.get_settings", lambda uid, p=persona: Settings(timezone="UTC", persona=p))
        body = _app(billing_route.router).get("/billing").json()
        assert body["recommended_plan"] == plan
    pro = next(p for p in body["plans"] if p["id"] == "pro")
    assert pro["best_for"].startswith("Busy owners and several outlets")
    plus = next(p for p in body["plans"] if p["id"] == "plus")
    assert plus["best_for"].startswith("A shop or small business")
