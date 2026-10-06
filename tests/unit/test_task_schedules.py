"""Easier schedules: weekdays / chosen days and one-off runs (next-run maths, plan
fit, mark_started switching a one-off off), titles made from the question, and the
preview the form shows as you type."""
from datetime import UTC, date, datetime
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from harness.api.auth import get_current_user
from harness.api.routes import settings as settings_route
from harness.db import tasks as tasks_db

# Tue 6 Oct 2026, 12:00 UTC = 17:30 in Kolkata
NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
MON, SAT = 0b0000001, 0b0100000


def test_weekdays_skip_the_weekend():
    # Fri 9 Oct 18:00 Kolkata: the 09:00 weekday run after it is Mon 12 Oct (03:30 UTC)
    fri_evening = datetime(2026, 10, 9, 12, 30, tzinfo=UTC)
    nxt = tasks_db.compute_next_run(None, "09:00", "Asia/Kolkata", after=fri_evening, days=tasks_db.WEEKDAYS)
    assert nxt == datetime(2026, 10, 12, 3, 30, tzinfo=UTC)
    # later today still counts: 18:00 Kolkata on Tue is ahead of 17:30
    assert tasks_db.compute_next_run(None, "18:00", "Asia/Kolkata", after=NOW, days=tasks_db.WEEKDAYS) == \
        datetime(2026, 10, 6, 12, 30, tzinfo=UTC)


def test_chosen_days_and_the_run_after_one():
    assert tasks_db.compute_next_run(None, "10:00", "UTC", after=NOW, days=SAT) == datetime(2026, 10, 10, 10, 0, tzinfo=UTC)
    # as the Saturday run starts, the next is the following Saturday
    sat = datetime(2026, 10, 10, 10, 0, tzinfo=UTC)
    assert tasks_db.compute_next_run(None, "10:00", "UTC", after=sat, ran=True, days=SAT) == \
        datetime(2026, 10, 17, 10, 0, tzinfo=UTC)


def test_a_one_off_runs_once_on_its_date():
    when = tasks_db.compute_next_run(None, "17:15", "Asia/Kolkata", after=NOW, run_on=date(2026, 10, 6))
    assert when == datetime(2026, 10, 6, 11, 45, tzinfo=UTC)
    assert tasks_db.compute_next_run(None, "17:15", "Asia/Kolkata", ran=True, run_on=date(2026, 10, 6)) is None


def test_how_often_each_schedule_runs_for_plan_checks():
    assert tasks_db.interval_minutes(None, "09:00", days=tasks_db.WEEKDAYS) == 24 * 60
    assert tasks_db.interval_minutes(None, "09:00", days=MON) == tasks_db.WEEK_MINUTES
    assert tasks_db.interval_minutes(None, "09:00", run_on=date(2026, 10, 6)) >= tasks_db.WEEK_MINUTES   # any plan


def _req(**kw):
    base = dict(every_minutes=None, daily_at="09:00", days=None, run_on=None, fit_plan=False)
    return SimpleNamespace(**{**base, **kw})


def test_free_fits_weekdays_to_once_a_week_and_allows_a_one_off(monkeypatch):
    from harness.billing import entitlements
    from harness.db import billing as billing_db
    monkeypatch.setattr(entitlements, "billing_enabled", lambda: True)
    monkeypatch.setattr(billing_db, "get_account", lambda uid: SimpleNamespace(plan="free"))
    assert settings_route._fit_schedule("7", _req(days=tasks_db.WEEKDAYS, fit_plan=True)) == (None, "09:00", MON)
    assert settings_route._fit_schedule("7", _req(run_on=date(2026, 10, 9))) == (None, "09:00", None)
    assert settings_route._fit_schedule("7", _req(days=SAT)) == (None, "09:00", SAT)


def test_titles_come_from_the_question():
    t = settings_route.title_from
    assert t("find a free slot this afternoon and block it as focus time") == "Find a free slot this afternoon and…"
    assert t("Brief me. Also check mail.") == "Brief me"
    assert t("   ") == "Task"


def test_the_form_preview(monkeypatch):
    async def connected(uid):
        return ["calendar", "github"]
    monkeypatch.setattr("harness.connectors.auto.connected_apps", connected)
    app = FastAPI()
    app.include_router(settings_route.router)
    app.dependency_overrides[get_current_user] = lambda: {"user_id": "7", "role": "user"}
    r = TestClient(app).post("/tasks/preview", json={"question": "Create an event for my PR review"}).json()
    assert r["apps"] == ["calendar", "github"] and r["title"] == "Create an event for my PR review"
    assert r["asks_first"] == ["github"] and r["lead_minutes"] == 5       # GitHub writes still ask


def test_a_task_that_asks_first_runs_five_minutes_early():
    # daily 09:00 UTC, asked at 07:00: plain tasks run at 09:00, GitHub ones at 08:55
    seven = datetime(2026, 10, 6, 7, 0, tzinfo=UTC)
    assert tasks_db.next_for(None, "09:00", "UTC", ["calendar"], after=seven) == datetime(2026, 10, 6, 9, 0, tzinfo=UTC)
    early = tasks_db.next_for(None, "09:00", "UTC", ["github"], after=seven)
    assert early == datetime(2026, 10, 6, 8, 55, tzinfo=UTC)
    # as that early run starts, the next is tomorrow's 08:55 -- not the same slot again
    assert tasks_db.next_for(None, "09:00", "UTC", ["github"], after=early, ran=True) == \
        datetime(2026, 10, 7, 8, 55, tzinfo=UTC)
    # interval tasks have no "time they picked", so no lead
    assert tasks_db.next_for(60, None, "UTC", ["github"], after=seven) == datetime(2026, 10, 6, 8, 0, tzinfo=UTC)


def test_a_task_that_sends_email_runs_early_one_that_reads_it_does_not():
    seven = datetime(2026, 10, 6, 7, 0, tzinfo=UTC)
    reads = tasks_db.next_for(None, "09:00", "UTC", ["gmail"], after=seven, question="Summarise unread emails")
    sends = tasks_db.next_for(None, "09:00", "UTC", ["gmail"], after=seven, question="Send Priya the report")
    assert reads == datetime(2026, 10, 6, 9, 0, tzinfo=UTC) and sends == datetime(2026, 10, 6, 8, 55, tzinfo=UTC)
