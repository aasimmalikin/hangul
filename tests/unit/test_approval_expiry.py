"""A new message in a chat expires the approvals still waiting in it, and
approving an expired one is a clear 409, never a late execution."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from harness.checkpoint import store as store_mod
from harness.checkpoint.store import CheckpointStore
from harness.db.models import Thread
from tests.unit.test_resilience_backend import approve_app, pending_checkpoint  # noqa: F401


@compiles(JSONB, "sqlite")
def _jsonb_as_json(_type, _compiler, **_kw):
    return "JSON"


@pytest.fixture
def db(monkeypatch):
    engine = create_engine("sqlite://")
    Thread.__table__.create(engine)
    monkeypatch.setattr(store_mod, "SessionLocal", sessionmaker(engine))
    return sessionmaker(engine)


def _thread(s, tid, *, conv="c1", user="alice", status="pending_approval"):
    s.add(Thread(thread_id=tid, conversation_id=conv, user_id=user, status=status, message=[], completed_calls={},
                 pending_tool={"name": "gmail__send_message"} if status == "pending_approval" else None, step=1))


def test_a_new_message_expires_the_chats_waiting_approvals(db):
    with db() as s:
        _thread(s, "old-1")
        _thread(s, "old-2")
        _thread(s, "other-chat", conv="c2")                 # a different chat keeps its approval
        _thread(s, "someone-else", user="bob")              # so does another user's run
        _thread(s, "done", status="done")
        _thread(s, "new-run")                               # the run being started now
        s.commit()
    assert CheckpointStore().expire_pending("c1", "alice", keep_thread_id="new-run") == 2
    with db() as s:
        rows = {t.thread_id: (t.status, t.pending_tool) for t in s.query(Thread)}
    assert rows["old-1"] == ("expired", None) and rows["old-2"] == ("expired", None)
    assert rows["other-chat"][0] == rows["someone-else"][0] == rows["new-run"][0] == "pending_approval"
    assert rows["done"][0] == "done"
    # nothing left to take: an expired (or finished) run can't be claimed, and so never executed
    assert CheckpointStore().claim_pending("old-1", "alice") is None
    assert CheckpointStore().claim_pending("done", "alice") is None


def test_claim_takes_a_waiting_action_once(db):
    with db() as s:
        _thread(s, "run-1")
        s.commit()
    first = CheckpointStore().claim_pending("run-1", "alice")
    assert first is not None and first.pending_tool == {"name": "gmail__send_message"}
    # a double-click / retry: the row now holds JSON null, which must not read as claimable
    assert CheckpointStore().claim_pending("run-1", "alice") is None
    assert CheckpointStore().claim_pending("run-1", "bob") is None


def test_approving_an_expired_request_says_so(approve_app):
    app, store, _, _, _ = approve_app
    cp = pending_checkpoint("run-1", "alice")
    cp.pending_tool, cp.status = None, "expired"
    store.save(cp)
    r = TestClient(app).post("/approve", json={"approval_id": "run-1", "decision": "approve"})
    assert r.status_code == 409 and r.headers["X-Reason"] == "approval_expired"
    assert "expired because the chat moved on" in r.json()["detail"]
    # another user's expired run still reads as not found
    cp.user_id = "bob"
    store.save(cp)
    assert TestClient(app).post("/approve", json={"approval_id": "run-1", "decision": "approve"}).status_code == 404
