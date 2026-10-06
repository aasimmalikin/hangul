"""The Today screen (GET /today) and connected apps that "just work"
(connectors/auto.py). Fakes only."""
import asyncio
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


@pytest.mark.parametrize("question,github", [
    ("Open an issue in aasimmalikin/hangul-test titled 'Hangul test'", True),
    ("Create a new issue for the login bug", True),
    ("Summarise issue #12", True),
    ("What's the status of acme/app#4?", True),
    ("Show me the README of acme/app", True),
    ("Did CI pass on the latest PR in acme/app?", True),
    ("Comment on acme/app issue 7 that it's fixed", True),
    ("I have an issue with my laptop", False),
    ("Review my essay for grammar", False),
    ("Commit to a gym schedule for me", False),
    ("Check the issues with my diet plan", False),
    ("Is 3/4 cup of rice enough? I have an issue with portions", False),
    ("Read https://example.com/docs/page and summarise the issues it lists", False),
])
def test_router_spots_github_without_the_word(question, github):
    assert ("github" in auto.route(question, ["github"])) is github


def test_router_never_turns_on_an_app_that_is_not_connected():
    assert auto.route("Summarise my unread emails and Slack", ["slack"]) == ["slack"]
    assert auto.route("Email Priya the report", []) == []


# ------------------------------------------------------------- /today

@pytest.fixture
def client(monkeypatch):
    now = datetime.now(UTC)
    monkeypatch.setattr("harness.db.settings.get_settings",
                        lambda uid: SimpleNamespace(timezone="Asia/Kolkata", city="Pune", display_name="Aasim Malik", home_address=""))

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

    async def replies(uid):
        return []
    monkeypatch.setattr(today_route, "_replies", replies)
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


def test_quick_answers_from_the_database_without_any_slow_call(client, monkeypatch):
    async def must_not_run(*a, **k):
        raise AssertionError("quick=1 made a slow call")
    for name in ("_weather", "_calendar", "_mail", "_replies", "_birthdays"):
        monkeypatch.setattr(today_route, name, must_not_run)
    monkeypatch.setattr(auto, "connected_apps", must_not_run)
    b = client.get("/today?quick=1").json()
    assert b["partial"] is True
    assert b["name"] == "Aasim" and b["todos"][0]["text"] == "Milk" and b["approvals"][0]["run_id"] == "r1"
    assert b["weather"] is None and b["events"] is None and b["replies"] is None


def test_quick_uses_what_the_full_brief_cached(client):
    assert client.get("/today").json()["partial"] is False             # warms the cache
    b = client.get("/today?quick=1").json()
    assert b["weather"]["place"] == "Pune" and b["events"][0]["summary"] == "Standup"


def test_slow_sections_run_side_by_side(client, monkeypatch):
    import time

    async def slow_calendar(uid, tz):
        await asyncio.sleep(0.4)
        return []

    async def slow_replies(uid):
        await asyncio.sleep(0.4)
        return []
    monkeypatch.setattr(today_route, "_calendar", slow_calendar)
    monkeypatch.setattr(today_route, "_replies", slow_replies)
    today_route._cache.clear()
    t0 = time.monotonic()
    client.get("/today")
    assert time.monotonic() - t0 < 0.75                                # not 0.4 + 0.4 one after the other


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


# ------------------------------------------------------------- leave by, birthdays, tomorrow

def _fixed_now(monkeypatch, local: str):
    """Freeze today.py's clock at an Asia/Kolkata wall time."""
    from zoneinfo import ZoneInfo
    frozen = datetime.fromisoformat(local).replace(tzinfo=ZoneInfo("Asia/Kolkata"))

    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return frozen.astimezone(tz) if tz else frozen
    monkeypatch.setattr(today_route, "datetime", Frozen)
    return frozen


def test_next_with_place_skips_video_links_all_day_and_far_events():
    from zoneinfo import ZoneInfo
    now = datetime(2026, 10, 3, 9, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    events = [
        {"summary": "Call", "start": "2026-10-03T09:30:00+05:30", "location": "https://meet.google.com/abc"},
        {"summary": "Holiday", "start": "2026-10-03", "all_day": True, "location": "Goa"},
        {"summary": "Started", "start": "2026-10-03T08:30:00+05:30", "location": "Office"},
        {"summary": "Dentist", "start": "2026-10-03T11:00:00+05:30", "location": "FC Road, Pune"},
    ]
    assert today_route.next_with_place(events, now)["summary"] == "Dentist"
    far = [{"summary": "Late", "start": "2026-10-04T08:00:00+05:30", "location": "Office"}]
    assert today_route.next_with_place(far, now) is None            # 23 h away


def test_leave_by_needs_a_home_then_times_the_trip(monkeypatch):
    from zoneinfo import ZoneInfo
    now = datetime(2026, 10, 3, 9, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    events = [{"summary": "Dentist", "start": "2026-10-03T11:00:00+05:30", "location": "FC Road, Pune"}]
    card = asyncio.run(today_route._leave_by("", events, now))
    assert card["needs_home"] is True and card["summary"] == "Dentist"

    async def route(home, place):
        return {"minutes": 25, "link": "https://maps.example"}
    monkeypatch.setattr(today_route, "_route", route)
    card = asyncio.run(today_route._leave_by("Baner, Pune", events, now))
    # 11:00 - 25 min drive - 10 min buffer
    assert card["leave_at"].startswith("2026-10-03T10:25") and card["late"] is False and card["minutes"] == 25
    late = asyncio.run(today_route._leave_by("Baner, Pune", events, now.replace(hour=10, minute=40)))
    assert late["late"] is True and late["leave_at"].startswith("2026-10-03T10:40")   # "leave now"


def test_birthdays_in_the_coming_week():
    from datetime import date

    from harness.connectors.google_rest import upcoming
    person = lambda name, **d: {"names": [{"displayName": name}], "birthdays": [{"date": d}]}   # noqa: E731
    people = [person("Priya", month=10, day=5, year=1995), person("Ravi", month=10, day=3),
              person("Old", month=9, day=1), person("Leap", month=2, day=29), {"names": [{"displayName": "No date"}]}]
    got = upcoming(people, date(2026, 10, 3), 7)
    assert [(b["name"], b["in_days"]) for b in got] == [("Ravi", 0), ("Priya", 2)]
    assert got[1]["turns"] == 31 and "turns" not in got[0]
    # 29 Feb is shown on the 28th in a non-leap year
    assert upcoming(people, date(2027, 2, 25), 7)[0] == {"name": "Leap", "date": "2027-02-28", "in_days": 3}
    # year end wraps to January
    assert upcoming([person("Jan", month=1, day=2)], date(2026, 12, 30), 7)[0]["in_days"] == 3


def test_evening_adds_tomorrow_and_the_new_cards(client, monkeypatch):
    _fixed_now(monkeypatch, "2026-10-03T19:00:00")

    async def connected(uid):
        return ["gmail", "calendar", "contacts"]
    monkeypatch.setattr(auto, "connected_apps", connected)

    async def calendar(uid, tz):
        return [{"summary": "Dinner", "start": "2026-10-03T20:30:00+05:30", "location": "Koregaon Park, Pune"},
                {"summary": "Flight", "start": "2026-10-04T07:10:00+05:30", "location": "Pune Airport"}]
    monkeypatch.setattr(today_route, "_calendar", calendar)

    async def birthdays(uid, day):
        return [{"name": "Priya", "date": "2026-10-04", "in_days": 1}]
    monkeypatch.setattr(today_route, "_birthdays", birthdays)
    monkeypatch.setattr(personal, "list_reminders", lambda uid, st, lim: [
        ReminderOut(4, "Pack bag", "2026-10-04T06:00:00+05:30", "pending", None)])
    today_route._cache.clear()
    b = client.get("/today").json()
    assert [e["summary"] for e in b["events"]] == ["Dinner"]
    assert b["tomorrow"]["date_label"] == "Sunday, 04 October"
    assert [e["summary"] for e in b["tomorrow"]["events"]] == ["Flight"]
    assert [r["text"] for r in b["tomorrow"]["reminders"]] == ["Pack bag"]
    assert b["reminders"] == []                                   # tomorrow's reminder isn't "today"
    assert b["leave_by"]["summary"] == "Dinner" and b["leave_by"]["needs_home"] is True
    assert b["birthdays"][0]["name"] == "Priya"


def test_no_tomorrow_before_six(client, monkeypatch):
    _fixed_now(monkeypatch, "2026-10-03T11:00:00")
    today_route._cache.clear()
    b = client.get("/today").json()
    assert b["tomorrow"] is None and b["birthdays"] is None      # Contacts not connected in this fixture


def test_needs_you_mail_leaves_out_your_own_and_hanguls_emails():
    from harness.api.routes.today import mail_query
    q = mail_query("Hangul <official@hangul.site>")
    assert "is:unread" in q and "newer_than:2d" in q
    assert "-from:me" in q                                   # notes and tests you emailed yourself
    assert q.endswith("-from:official@hangul.site")          # reminders, the brief, task results
    assert mail_query(None).endswith("-from:me")             # no sending address configured
    assert mail_query("official@hangul.site").endswith("-from:official@hangul.site")
