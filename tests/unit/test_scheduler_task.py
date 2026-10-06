"""scheduler.run_task and the approval sweep: a scheduled question runs unattended and
is routed to the user's connected apps like a chat message; a run that waits for the
user always tells them (whatever "email me" says), with Approve/Reject on WhatsApp;
and a waiting action expires when the task runs again or after a day."""
import asyncio
import contextlib
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from harness import scheduler


@pytest.fixture
def env(monkeypatch):
    calls = {"expired": [], "status": {}, "email": [], "push": [], "whatsapp": [], "finished": {}}
    outcome = {"pending": None}

    async def build_and_run(req, user_id, *, unattended=False):
        calls["req"], calls["unattended"] = req, unattended
        result = SimpleNamespace(pending_tool=outcome["pending"], answer="Prepared the event; it needs your OK.")
        return SimpleNamespace(result=result, run=SimpleNamespace(run_id="r2"), conversation_id="c2")

    @contextlib.asynccontextmanager
    async def slot(_uid):
        yield

    async def no_episode(*a, **k):
        return None

    async def email(task, answer, *, needs_approval=False, approval=None):
        calls["email"].append(needs_approval)
        calls["approval"] = approval
        return True

    async def push_result(user_id, title, answer, *, conversation_id, needs_approval=False, url=None, pending=None):
        calls["push"].append((conversation_id, needs_approval))
        calls["push_url"] = url
        return 1

    async def whatsapp(user_id, kind, text, *, title="", pending=None, run_id=None):
        calls["whatsapp"].append((pending, run_id))
        return outcome.get("on_whatsapp", True)          # False = Free plan, or WhatsApp not linked

    class Store:
        def expire_run(self, run_id, user_id):
            calls["expired"].append(run_id)
            return run_id != "already-decided"

    from harness import push
    from harness.api import concurrency
    from harness.api.routes import ask
    from harness.db import episodes
    from harness.db import tasks as tasks_db
    from harness.whatsapp import service
    monkeypatch.setattr(ask, "_build_and_run", build_and_run)
    monkeypatch.setattr(concurrency, "run_slot", slot)
    monkeypatch.setattr(episodes, "store_episode", no_episode)
    monkeypatch.setattr(tasks_db, "mark_started", lambda *a, **k: None)
    monkeypatch.setattr(tasks_db, "mark_finished", lambda tid, **k: calls["finished"].update(k))
    monkeypatch.setattr(tasks_db, "set_status", lambda tid, st: calls["status"].__setitem__(tid, st))
    monkeypatch.setattr(scheduler, "_weekly_only", lambda uid: False)
    monkeypatch.setattr(scheduler, "_store", lambda: Store())
    monkeypatch.setattr(scheduler, "email_result", email)
    monkeypatch.setattr(push, "task_result", push_result)
    monkeypatch.setattr(service, "notify", whatsapp)
    return calls, outcome, tasks_db


def _task(**kw):
    base = dict(id=8, user_id=3, title="Test", question="Create an event at 4pm and email me", connectors=[],
                mode="default", deliver_email=False, last_status="done", last_run_id="r1")
    return SimpleNamespace(**{**base, **kw})


def test_a_task_runs_unattended_with_the_apps_its_question_needs(env):
    calls, _, _ = env
    asyncio.run(scheduler.run_task(_task(), tz="Asia/Kolkata"))
    assert calls["unattended"] is True
    assert calls["req"].connectors_auto is True and calls["req"].connectors == []
    assert calls["finished"]["status"] == "done"
    assert calls["email"] == calls["push"] == calls["whatsapp"] == []      # "email me" off, nothing waiting


def test_on_plus_a_waiting_action_goes_to_whatsapp(env):
    calls, outcome, _ = env
    outcome["pending"] = {"name": "gmail__send_message", "arguments": {"to": "priya@x.in", "subject": "Report"}}
    asyncio.run(scheduler.run_task(_task(deliver_email=False), tz="Asia/Kolkata"))
    assert calls["finished"]["status"] == "needs_approval"
    assert calls["whatsapp"] == [(outcome["pending"], "r2")]                # Approve / Reject for run r2
    assert calls["email"] == []                                           # WhatsApp took it
    assert calls["push"] == [("c2", True)]


def test_on_free_a_waiting_action_comes_by_email(env):
    calls, outcome, _ = env
    outcome["pending"] = {"name": "gmail__send_message", "arguments": {"to": "priya@x.in", "subject": "Report"}}
    outcome["on_whatsapp"] = False
    asyncio.run(scheduler.run_task(_task(), tz="Asia/Kolkata"))
    assert calls["email"] == [True]
    # the email and the notification carry a signed link to this run's Approve / Reject page
    from harness import approval_links
    link = calls["approval"]["url"]
    assert approval_links.read(link.rsplit("/approve/", 1)[1]) == ("r2", "3")
    assert calls["push_url"] == "/approve/" + link.rsplit("/approve/", 1)[1]
    assert calls["approval"]["card"]["title"] == "Send this email?"


def test_a_result_is_sent_only_when_asked(env):
    calls, _, _ = env
    asyncio.run(scheduler.run_task(_task(deliver_email=True), tz="UTC"))
    assert calls["email"] == [False] and calls["whatsapp"] == [(None, None)]


def test_the_previous_waiting_run_expires_when_the_task_runs_again(env):
    calls, _, _ = env
    asyncio.run(scheduler.run_task(_task(last_status="needs_approval", last_run_id="r1"), tz="UTC"))
    assert calls["expired"] == ["r1"]
    calls["expired"].clear()
    asyncio.run(scheduler.run_task(_task(last_status="done", last_run_id="r1"), tz="UTC"))
    assert calls["expired"] == []                                         # nothing was waiting


def test_actions_waiting_more_than_a_day_expire(env, monkeypatch):
    calls, _, tasks_db = env
    asked = {}

    def waiting_since(before):
        asked["before"] = before
        return [(8, 3, "r-old"), (9, 3, "already-decided")]
    monkeypatch.setattr(tasks_db, "waiting_since", waiting_since)
    now = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)
    assert asyncio.run(scheduler.expire_stale_approvals(now)) == 1
    assert asked["before"] == datetime(2026, 10, 6, 12, 0, tzinfo=UTC)    # 24 hours
    assert calls["status"] == {8: "expired", 9: "done"}                   # decided ones just stop "waiting"
