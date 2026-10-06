"""PUT /settings keeps the stored home address when a screen doesn't send it
(older pages and the Today city box PUT settings without the field)."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from harness.api.auth import get_current_user
from harness.api.routes import settings as settings_route
from harness.db.settings import Settings


def test_home_address_survives_a_put_that_omits_it(monkeypatch):
    stored = {"7": Settings(timezone="Asia/Kolkata", city="Pune", home_address="Baner, Pune")}
    monkeypatch.setattr(settings_route, "get_settings", lambda uid: stored[uid])

    def save(uid, values):
        stored[uid] = values
        return values
    monkeypatch.setattr(settings_route, "save_settings", save)
    app = FastAPI()
    app.include_router(settings_route.router)
    app.dependency_overrides[get_current_user] = lambda: {"user_id": "7"}
    c = TestClient(app)
    body = {"timezone": "Asia/Kolkata", "city": "Mumbai"}
    assert c.put("/settings", json=body).json()["home_address"] == "Baner, Pune"
    assert c.put("/settings", json={**body, "home_address": "Bandra, Mumbai"}).json()["home_address"] == "Bandra, Mumbai"
    assert c.put("/settings", json={**body, "home_address": ""}).json()["home_address"] == ""     # cleared on purpose
