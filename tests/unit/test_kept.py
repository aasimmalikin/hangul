"""The Kept tab: rows a run creates remember their chat and the user's words,
outward actions are logged once and only when they happened, and /kept
shows each instruction in the right state -- the caller's only."""
import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from harness import provenance
from harness.api.auth import get_current_user
from harness.api.routes import kept as kept_route
from harness.db import kept as kept_db
from harness.db import memory as memory_db
from harness.db import personal
from harness.db.models import (
    Conversation,
    KeptAction,
    Note,
    Reminder,
    ScheduledTask,
    Thread,
    TodoItem,
    UserMemory,
)
from harness.policy.audit import AuditLog
from harness.policy.guarded import guarded_dispatch
from harness.policy.policy import ToolPolicy
from harness.policy.tiers import Tier
from harness.tools.base import Tool

NOW = datetime(2026, 10, 5, 14, 0, tzinfo=UTC)


@compiles(JSONB, "sqlite")
def _jsonb_as_json(_type, _compiler, **_kw):
    return "JSON"


@pytest.fixture
def db(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    for m in (Conversation, KeptAction, Note, Reminder, ScheduledTask, Thread, TodoItem, UserMemory):
        m.__table__.create(engine)
    maker = sessionmaker(engine)
    for mod in (kept_db, personal, memory_db):
        monkeypatch.setattr(mod, "SessionLocal", maker)
    return maker


# ------------------------------------------------------------ provenance

def test_rows_made_in_a_run_remember_the_chat_and_the_words(db):
    with provenance.source("7", "conv1", "  Remind me to   call mum at 6 "):
        personal.add_reminder("7", "Call mum", NOW + timedelta(hours=4))
        personal.add_todos("7", "Shopping", ["milk", "atta"])
        personal.add_note("7", "Car service at 42,000 km")
        memory_db.remember("7", "Mum lives in Srinagar")
    personal.add_note("7", "typed on the page")               # no run open: no source
    with db() as s:
        for m in (Reminder, TodoItem, UserMemory):
            for r in s.query(m):
                assert (r.conversation_id, r.said) == ("conv1", "Remind me to call mum at 6")
        notes = {n.text: (n.conversation_id, n.said) for n in s.query(Note)}
    assert notes["typed on the page"] == (None, None)
    assert notes["Car service at 42,000 km"] == ("conv1", "Remind me to call mum at 6")
    assert provenance.current() is None                      # closed after the run


@pytest.mark.parametrize("stored,shown", [("00:05", "12:05 AM"), ("08:00", "8:00 AM"), ("12:00", "12:00 PM"),
                                          ("16:10", "4:10 PM"), ("23:59", "11:59 PM")])
def test_task_times_read_as_am_pm(stored, shown):
    assert kept_db._clock(stored) == shown


def test_new_schedules_read_plainly():
    from datetime import date
    t = lambda **kw: ScheduledTask(daily_at="09:15", every_minutes=None, **kw)  # noqa: E731
    assert kept_db._schedule(t(days=0b0011111)) == "Every weekday at 9:15 AM"
    assert kept_db._schedule(t(days=0b0100000)) == "Every Sat at 9:15 AM"
    assert kept_db._schedule(t(days=0b0010101)) == "Mon, Wed, Fri at 9:15 AM"
    assert kept_db._schedule(t(run_on=date(2026, 10, 6))) == "Once on Tue 6 Oct at 9:15 AM"


def test_said_is_capped():
    with provenance.source("7", None, "x" * 2000):
        assert len(provenance.current().said) == provenance.SAID_MAX


# ------------------------------------------------------- action recording

def _tool(name, reply="Sent message 18c.", stub=False):
    async def handler(**_):
        return reply
    return Tool(name=name, description="", parameter={"type": "object"}, handler=handler, upgrade_stub=stub)


def _dispatch(tool, args=None):
    policy = ToolPolicy(tiers={tool.name: Tier.SAFE})
    return asyncio.run(guarded_dispatch(tool, args or {}, policy, AuditLog("/dev/null")))


def _in_run(fn):
    async def go():
        with provenance.source("7", "conv1", "Email Priya the Q3 deck"):
            policy = ToolPolicy(tiers={fn.name: Tier.SAFE})
            return await guarded_dispatch(fn, {"to": "priya@example.com", "subject": "Q3 deck"}, policy,
                                          AuditLog("/dev/null"))
    return asyncio.run(go())


def test_a_sent_email_is_logged_with_its_source(db):
    _in_run(_tool("gmail__send_message"))
    with db() as s:
        (a,) = s.query(KeptAction).all()
    assert (a.user_id, a.conversation_id, a.said, a.app) == ("7", "conv1", "Email Priya the Q3 deck", "Email")
    assert a.did == "Sent an email to priya@example.com: Q3 deck"


@pytest.mark.parametrize("tool", [
    _tool("gmail__search_messages"),                          # a read
    _tool("gmail__send_message", reply="[tool error] 403"),   # failed, reported as text
    _tool("gmail__send_message", reply="Error: no token"),
    _tool("gmail__send_message", stub=True),                  # an upgrade card, nothing sent
    _tool("reminders"),                                       # has its own row
])
def test_only_real_outward_actions_are_logged(db, tool):
    _in_run(tool)
    with db() as s:
        assert s.query(KeptAction).count() == 0


def test_no_run_no_log(db):
    _dispatch(_tool("gmail__send_message"))
    with db() as s:
        assert s.query(KeptAction).count() == 0


def test_run_question_skips_approve_follow_ups():
    msgs = [{"role": "system", "content": "…"}, {"role": "user", "content": "Email Priya the deck"},
            {"role": "assistant", "content": None, "tool_calls": []},
            {"role": "user", "content": "Briefly confirm what was just done, in one sentence."}]
    assert kept_db.run_question(msgs) == "Email Priya the deck"
    assert kept_db.run_question([{"role": "user", "content": [{"type": "text", "text": "hi there"}]}]) == "hi there"
    assert kept_db.run_question([]) == ""


# ------------------------------------------------------------- the list

def _seed(s):
    s.add_all([
        Conversation(id="conv1", user_id="7", title="Q3"),
        Conversation(id="gone", user_id="7", title="deleted", active=False),
        Thread(thread_id="run-1", conversation_id="conv1", user_id="7", status="pending_approval", step=1,
               completed_calls={}, updated_at=NOW - timedelta(minutes=2),
               message=[{"role": "user", "content": "Email Priya the Q3 deck"}],
               pending_tool={"name": "gmail__send_message", "arguments": {"to": "priya@x.in", "subject": "Q3"}}),
        Thread(thread_id="run-ask", conversation_id="conv1", user_id="7", status="pending_approval", step=1,
               completed_calls={}, updated_at=NOW, message=[], pending_tool={"name": "ask_user"}),
        Thread(thread_id="run-hidden", conversation_id="gone", user_id="7", status="pending_approval", step=1,
               completed_calls={}, updated_at=NOW, message=[], pending_tool={"name": "slack__send_message"}),
        Thread(thread_id="run-bob", conversation_id=None, user_id="8", status="pending_approval", step=1,
               completed_calls={}, updated_at=NOW, message=[], pending_tool={"name": "gmail__send_message"}),
        Reminder(user_id=7, text="Call mum", due_at=NOW + timedelta(hours=4), said="Remind me to call mum at 6",
                 conversation_id="conv1"),
        Reminder(user_id=7, text="Pay rent", due_at=NOW - timedelta(days=1), status="sent"),
        Reminder(user_id=7, text="Old", due_at=NOW - timedelta(days=30), status="sent"),
        Reminder(user_id=7, text="Nope", due_at=NOW + timedelta(hours=1), status="cancelled"),
        Reminder(user_id=8, text="Bob's", due_at=NOW + timedelta(hours=1)),
        ScheduledTask(user_id=7, title="Morning brief", question="Brief me every morning", daily_at="08:00",
                      enabled=True, next_run_at=NOW + timedelta(hours=18), last_run_at=NOW - timedelta(hours=6),
                      last_status="done", deliver_email=True, connectors=[], last_run_id="run-1"),
        KeptAction(user_id="7", conversation_id="conv1", said="September expenses as a PDF", tool="create_file",
                   app="File", did="Made “Expenses” (PDF)", created_at=NOW - timedelta(days=1)),
        KeptAction(user_id="8", tool="create_file", app="File", did="Bob's file", created_at=NOW),
        TodoItem(user_id=7, list_name="Shopping", text="milk"),
        TodoItem(user_id=7, list_name="Shopping", text="eggs", done=True),
        Note(user_id=7, text="Gift idea: pashmina", said="note a gift idea for mum"),
        UserMemory(user_id=7, kind="fact", content="Mum lives in Srinagar"),
        UserMemory(user_id=7, kind="fact", content="forgotten", active=False),
    ])
    s.commit()


def test_timeline_puts_each_instruction_in_its_state(db):
    with db() as s:
        _seed(s)
    out = kept_db.kept("7", now=NOW)
    by = {i["id"]: i for i in out["items"]}
    assert set(by) == {"approval:run-1", "reminder:1", "reminder:2", "task:1", "task_run:1", "action:1"}
    assert by["approval:run-1"]["state"] == "needs_you"
    assert by["approval:run-1"]["said"] == "Email Priya the Q3 deck"
    assert by["approval:run-1"]["did"] == "Send an email to priya@x.in: Q3"
    assert by["approval:run-1"]["conversation_id"] == "conv1"
    assert by["reminder:1"]["state"] == "coming" and by["reminder:1"]["said"] == "Remind me to call mum at 6"
    assert by["reminder:2"]["state"] == "done"                 # went off yesterday
    assert by["task:1"]["state"] == "coming" and "Every day at 8:00 AM, emailed to you" in by["task:1"]["did"]
    assert by["task_run:1"]["state"] == "done" and by["task_run:1"]["did"] == "Ran: Morning brief"
    assert by["task_run:1"]["conversation_id"] == "conv1"     # the run's chat, so "Open the chat" works
    assert by["action:1"]["state"] == "done"
    assert out["needs_you"] == 1
    assert out["holding"] == {"lists": {"Shopping": 1}, "notes": 1, "memories": 1}
    whens = [i["when"] for i in out["items"]]
    assert whens == sorted(whens)                              # oldest first; the page finds "now"


def test_search_reaches_all_time_and_undated_things(db):
    with db() as s:
        _seed(s)
    out = kept_db.kept("7", q="What did I ask about mum?", now=NOW)
    ids = {i["id"] for i in out["items"]}
    # the reminder by its words, the note by what was said, the memory by its content
    assert ids == {"reminder:1", "note:1", "memory:1"}
    assert kept_db.kept("7", q="pashmina", now=NOW)["items"][0]["state"] == "kept"
    assert {i["id"] for i in kept_db.kept("7", q="old", now=NOW)["items"]} == {"reminder:3"}  # beyond the week
    assert kept_db.kept("8", q="mum", now=NOW)["items"] == []  # never another user's


def test_badge_counts_only_real_approvals(db):
    with db() as s:
        _seed(s)
    assert kept_db.needs_you_count("7", now=NOW) == 1
    assert kept_db.needs_you_count("9", now=NOW) == 0


def test_route(db, monkeypatch, tmp_path):
    with db() as s:
        _seed(s)
    (tmp_path / "expenses.pdf").write_bytes(b"%PDF")
    monkeypatch.setattr("harness.tools.builtin.files.user_folder", lambda uid: tmp_path)
    app = FastAPI()
    app.include_router(kept_route.router)
    app.dependency_overrides[get_current_user] = lambda: {"user_id": "7", "role": "user"}
    c = TestClient(app)
    body = c.get("/kept").json()
    assert body["holding"]["files"] == 1 and body["needs_you"] == 1
    assert c.get("/kept/count").json() == {"needs_you": 1}
    assert c.get("/kept", params={"q": "x" * 201}).status_code == 422
