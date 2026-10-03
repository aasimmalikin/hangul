"""The Today screen (GET /today) and connected apps that "just work"
(connectors/auto.py). Fakes only."""
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from harness.api.auth import get_current_user
from harness.api.routes import today as today_route
from harness.connectors import auto
from harness.db import personal
from harness.db.personal import ReminderOut, TodoOut

ALL = ["gmail", "calendar", "contacts", "drive", "docs", "sheets", "github", "notion", "slack"]


@pytest.mark.parametrize("question,expected", [
    ("Summarise my unread emails", ["gmail"]),
    ("When am I free on Thursday?", ["calendar"]),
    ("Move my 3pm standup to 4pm", ["calendar"]),
    ("Email Priya the report", ["gmail", "contacts"]),
    ("Add today's lunch to my budget sheet", ["sheets"]),
    ("Which PRs are waiting for my review?", ["github"]),
    ("What did the team say in the design channel on Slack?", ["slack"]),
    ("Plan my day", ["gmail", "calendar"]),               # planning a day needs its calendar and mail
    ("What's 15% of 2400?", []),
    ("Give me my morning brief", ["gmail", "calendar"]),
])
def test_router_picks_only_what_the_message_needs(question, expected):
    assert sorted(auto.route(question, ALL)) == sorted(expected)


def test_router_never_turns_on_an_app_that_is_not_connected():
    assert auto.route("Summarise my unread emails and Slack", ["slack"]) == ["slack"]
    assert auto.route("Email Priya the report", []) == []


# ------------------------------------------------------------- /today

@pytest.fixture
def client(monkeypatch):
    now = datetime.now(UTC)
    monkeypatch.setattr("harness.db.settings.get_settings",
                        lambda uid: SimpleNamespace(timezone="Asia/Kolkata", city="Pune", display_name="Aasim Malik"))

    async def connected(uid):
        return ["gmail", "calendar"]
    monkeypatch.setattr(auto, "connected_apps", connected)
    monkeypatch.setattr(personal, "list_reminders", lambda uid, st, lim: [
        ReminderOut(1, "Call mom", (now - timedelta(minutes=5)).isoformat(), "sent", None),
        ReminderOut(2, "Pay rent", (now + timedelta(days=9)).isoformat(), "pending", None)])
    monkeypatch.setattr(personal, "list_todos", lambda uid: [TodoOut(3, "Shopping", "Milk", False)])
    monkeypatch.setattr(today_route, "_pending_approvals", lambda uid: [{"run_id": "r1", "conversation_id": "c1", "tool": "gmail__send_message", "since": None}])

    async def weather(city):
        return {"kind": "weather", "place": city, "current": {"temp": 27}}

    async def calendar(uid, tz):
        return [{"summary": "Standup", "start": "2026-10-02T10:00:00+05:30", "end": "2026-10-02T10:15:00+05:30"}]

    async def mail(uid):
        return [{"id": "m1", "from": "Bank", "subject": "Statement ready"}]
    monkeypatch.setattr(today_route, "_weather", weather)
    monkeypatch.setattr(today_route, "_calendar", calendar)
    monkeypatch.setattr(today_route, "_mail", mail)
    today_route._cache.clear()
    app = FastAPI()
    app.include_router(today_route.router)
    app.dependency_overrides[get_current_user] = lambda: {"user_id": "7"}
    return TestClient(app)


def test_today_brief_has_every_section(client):
    b = client.get("/today").json()
    assert b["name"] == "Aasim" and b["greeting"].startswith("Good ")
    assert b["weather"]["place"] == "Pune" and b["events"][0]["summary"] == "Standup"
    assert b["emails"][0]["subject"] == "Statement ready"
    assert [r["text"] for r in b["reminders"]] == ["Call mom"]          # next week's rent isn't "today"
    assert b["todos"][0]["text"] == "Milk" and b["approvals"][0]["run_id"] == "r1"


def test_unconnected_sections_are_null_and_a_failing_one_is_skipped(client, monkeypatch):
    async def none(uid):
        return []
    monkeypatch.setattr(auto, "connected_apps", none)

    async def broken(city):
        raise RuntimeError("weather down")
    monkeypatch.setattr(today_route, "_weather", broken)
    today_route._cache.clear()
    b = client.get("/today").json()
    assert b["events"] is None and b["emails"] is None and b["weather"] is None
    assert b["todos"][0]["text"] == "Milk"                                # the rest still renders
