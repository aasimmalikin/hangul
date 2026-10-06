"""Replies you owe: which Gmail threads count, the tool's output, and the
Today card (deduplicated against "Needs you")."""
import asyncio
from datetime import UTC, datetime, timedelta

from harness.connectors import replies as rep

ME = "aasim@example.com"
NOW = datetime(2026, 10, 3, 12, tzinfo=UTC)


def msg(frm="Priya <priya@acme.com>", to=ME, cc="", subject="Contract", age_h=48, labels=("INBOX",), **headers):
    hs = {"From": frm, "To": to, "Cc": cc, "Subject": subject, **headers}
    return {"labelIds": list(labels), "snippet": "Can you confirm…",
            "internalDate": str(int((NOW - timedelta(hours=age_h)).timestamp() * 1000)),
            "payload": {"headers": [{"name": k, "value": v} for k, v in hs.items() if v]}}


def thread(tid, *msgs):
    return {"id": tid, "messages": list(msgs)}


def test_a_direct_mail_waiting_two_days_is_owed():
    got = rep.owed([thread("t1", msg())], ME, NOW)
    assert got == [{"thread_id": "t1", "from": "Priya", "email": "priya@acme.com", "subject": "Contract",
                    "snippet": "Can you confirm…", "received": (NOW - timedelta(hours=48)).isoformat(),
                    "waiting_days": 2, "unread": False}]


def test_what_does_not_count():
    cases = {
        "answered": thread("a", msg(), msg(frm=f"Me <{ME}>", to="priya@acme.com", labels=("SENT",))),
        "too_new": thread("b", msg(age_h=5)),
        "too_old": thread("c", msg(age_h=24 * 20)),
        "only_cc": thread("d", msg(to="team@acme.com", cc=ME)),
        "archived": thread("e", msg(labels=())),
        "newsletter": thread("f", msg(**{"List-Unsubscribe": "<mailto:u@x.com>"})),
        "bulk": thread("g", msg(Precedence="bulk")),
        "auto": thread("h", msg(**{"Auto-Submitted": "auto-replied"})),
        "noreply": thread("i", msg(frm="Bank <no-reply@bank.com>")),
        "notifications": thread("j", msg(frm="GitHub <notifications@github.com>")),
        "promotions": thread("k", msg(labels=("INBOX", "CATEGORY_PROMOTIONS"))),
        "crowd": thread("l", msg(to=", ".join([ME] + [f"p{i}@x.com" for i in range(12)]))),
    }
    for name, t in cases.items():
        assert rep.owed([t], ME, NOW) == [], name


def test_longest_wait_first_and_case_insensitive_address():
    got = rep.owed([thread("new", msg(age_h=30)), thread("old", msg(age_h=100, to=ME.upper()))], ME, NOW)
    assert [r["thread_id"] for r in got] == ["old", "new"]


def test_the_tool_lists_them_for_the_model(monkeypatch):
    from harness.connectors.google_rest import make_google_tools

    async def fake(user_id, now, http=None, fresh=False):
        return rep.owed([thread("t1", msg())], ME, NOW)
    monkeypatch.setattr(rep, "replies_owed", fake)
    tool = next(t for t in make_google_tools("7") if t.name == "gmail__replies_owed")
    out = asyncio.run(tool.handler())
    assert "Priya <priya@acme.com>: Contract — waiting 2 day(s) [thread t1]" in out.text
    assert out.ui["kind"] == "gmail_messages" and out.ui["messages"][0]["thread_id"] == "t1"

    async def none(user_id, now, http=None, fresh=False):
        return []
    monkeypatch.setattr(rep, "replies_owed", none)
    assert "Nobody has been waiting" in asyncio.run(tool.handler())


def test_today_shows_replies_and_does_not_repeat_them_under_needs_you(monkeypatch):
    from types import SimpleNamespace

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from harness.api.auth import get_current_user
    from harness.api.routes import today as today_route
    from harness.connectors import auto
    from harness.db import personal

    monkeypatch.setattr("harness.db.settings.get_settings",
                        lambda uid: SimpleNamespace(timezone="UTC", city="", display_name="A", home_address=""))

    async def connected(uid):
        return ["gmail"]
    monkeypatch.setattr(auto, "connected_apps", connected)
    monkeypatch.setattr(personal, "list_reminders", lambda uid, st, lim: [])
    monkeypatch.setattr(personal, "list_todos", lambda uid: [])
    monkeypatch.setattr(today_route, "_pending_approvals", lambda uid: [])

    async def nothing(*a):
        return None

    async def mail(uid):
        return [{"id": "m1", "thread_id": "t1", "from": "Priya", "subject": "Contract"},
                {"id": "m2", "thread_id": "t2", "from": "Bank", "subject": "Statement"}]

    async def owed(uid):
        return [{"thread_id": "t1", "from": "Priya", "subject": "Contract", "waiting_days": 2}]
    monkeypatch.setattr(today_route, "_weather", nothing)
    monkeypatch.setattr(today_route, "_mail", mail)
    monkeypatch.setattr(today_route, "_replies", owed)
    today_route._cache.clear()
    app = FastAPI()
    app.include_router(today_route.router)
    app.dependency_overrides[get_current_user] = lambda: {"user_id": "7"}
    b = TestClient(app).get("/today").json()
    assert [r["thread_id"] for r in b["replies"]] == ["t1"]
    assert [m["thread_id"] for m in b["emails"]] == ["t2"]          # t1 isn't repeated under Needs you


def test_auto_routing_turns_gmail_on_for_reply_questions():
    from harness.connectors.auto import route
    for q in ("who do I owe a reply?", "which emails are waiting on me", "remind me to get back to Priya"):
        assert "gmail" in route(q, ["gmail", "calendar"]), q
