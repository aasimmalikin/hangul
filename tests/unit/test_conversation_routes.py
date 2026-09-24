"""The /conversations endpoints only ever show or change the caller's own
conversations, and a foreign id is indistinguishable from a missing one.

Runs against fakes: no Postgres. The ownership rule lives in the SQL WHERE
clause, so the fakes reproduce that shape rather than checking after the fact.
"""
from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from harness.api.auth import get_current_user
from harness.api.routes import conversations as conv_route

T = datetime(2026, 9, 24, tzinfo=timezone.utc)
OWNER = "7"


def _conv(cid, user_id=OWNER, title="Draft a note", active=True, **kw):
    return SimpleNamespace(
        id=cid, user_id=user_id, title=title, model=kw.get("model"), effort=kw.get("effort"),
        connectors=kw.get("connectors", []), mode=kw.get("mode", "default"),
        docs_only=kw.get("docs_only", False), summary_text=kw.get("summary_text", ""),
        summary_through_seq=0, next_seq=kw.get("next_seq", 0), security={},
        active_run_id=None, active_run_started_at=None, active=active,
        created_at=T, updated_at=T,
    )


def _msg(seq, role, content, **extra):
    return SimpleNamespace(seq=seq, role=role, content=content, extra=extra or {},
                           run_id="r1", tokens=1, created_at=T)


def _client(monkeypatch, convs, messages=None, user_id=OWNER):
    messages = messages or {}
    created = []

    def get_conversation(cid, uid):
        # ownership is part of the lookup, exactly as the WHERE clause is
        return next((c for c in convs if c.id == cid and c.user_id == uid and c.active), None)

    def list_conversations(uid, limit=50):
        return [c for c in convs if c.user_id == uid and c.active]

    def load_messages(cid, after_seq=0):
        return [m for m in messages.get(cid, []) if m.seq >= after_seq]

    def message_counts(ids):
        return {cid: len(messages.get(cid, [])) for cid in ids}

    def create_conversation(uid, **kw):
        created.append((uid, kw))
        return "newid"

    def rename_conversation(cid, uid, title):
        c = get_conversation(cid, uid)
        if c is None:
            return False
        c.title = title
        return True

    def deactivate_conversation(cid, uid):
        c = get_conversation(cid, uid)
        if c is None:
            return False
        c.active = False
        return True

    for name, fn in [
        ("get_conversation", get_conversation), ("list_conversations", list_conversations),
        ("load_messages", load_messages), ("message_counts", message_counts),
        ("create_conversation", create_conversation),
        ("rename_conversation", rename_conversation),
        ("deactivate_conversation", deactivate_conversation),
    ]:
        monkeypatch.setattr(conv_route, name, fn)

    app = FastAPI()
    app.include_router(conv_route.router)
    app.dependency_overrides[get_current_user] = lambda: {"user_id": user_id, "role": "user"}
    return TestClient(app), created


# ------------------------------------------------------------------ listing

def test_list_shows_only_the_callers_visible_conversations(monkeypatch):
    convs = [_conv("c1"), _conv("c2", user_id="8", title="someone else"),
             _conv("c3", title="hidden", active=False)]
    c, _ = _client(monkeypatch, convs)
    r = c.get("/conversations")
    assert r.status_code == 200
    assert [x["title"] for x in r.json()] == ["Draft a note"]


def test_list_reports_message_count_and_settings(monkeypatch):
    convs = [_conv("c1", model="gpt-5.5", effort="high", connectors=["arxiv"], mode="research")]
    msgs = {"c1": [_msg(0, "user", "hi"), _msg(1, "assistant", "hello")]}
    c, _ = _client(monkeypatch, convs, msgs)
    body = c.get("/conversations").json()[0]
    assert body["message_count"] == 2
    assert (body["model"], body["effort"], body["mode"]) == ("gpt-5.5", "high", "research")
    assert body["connectors"] == ["arxiv"]


# ------------------------------------------------------------------ transcript

def test_get_returns_the_transcript_in_order(monkeypatch):
    msgs = {"c1": [
        _msg(0, "user", "summarise report.txt"),
        _msg(1, "assistant", "reading it", tool_calls=[{"id": "t1", "type": "function"}]),
        _msg(2, "tool", "FILE BODY", tool_call_id="t1"),
        _msg(3, "assistant", "It covers Q3."),
    ]}
    c, _ = _client(monkeypatch, [_conv("c1")], msgs)
    r = c.get("/conversations/c1")
    assert r.status_code == 200
    body = r.json()
    assert [m["role"] for m in body["messages"]] == ["user", "assistant", "tool", "assistant"]
    assert body["messages"][1]["tool_calls"] == [{"id": "t1", "type": "function"}]
    assert body["messages"][2]["tool_call_id"] == "t1"


def test_transcript_truncates_a_big_tool_result(monkeypatch):
    """The browser draws a card; it does not need the whole payload."""
    big = "X" * (conv_route.TOOL_PREVIEW_CHARS * 5)
    msgs = {"c1": [_msg(0, "tool", big, tool_call_id="t1")]}
    c, _ = _client(monkeypatch, [_conv("c1")], msgs)
    content = c.get("/conversations/c1").json()["messages"][0]["content"]
    assert len(content) < len(big)
    assert content.endswith("…")


def test_transcript_passes_tool_ui_through(monkeypatch):
    msgs = {"c1": [_msg(0, "tool", "3 messages", tool_call_id="t1",
                        ui={"kind": "gmail_messages", "messages": []})]}
    c, _ = _client(monkeypatch, [_conv("c1")], msgs)
    assert c.get("/conversations/c1").json()["messages"][0]["ui"]["kind"] == "gmail_messages"


# ------------------------------------------------------------------ ownership

def test_someone_elses_conversation_is_404_not_403(monkeypatch):
    """A 403 would confirm the id exists. 404 for both, deliberately."""
    c, _ = _client(monkeypatch, [_conv("c1", user_id="8")])
    assert c.get("/conversations/c1").status_code == 404
    assert c.patch("/conversations/c1", json={"title": "mine now"}).status_code == 404
    assert c.delete("/conversations/c1").status_code == 404


def test_unknown_id_is_404(monkeypatch):
    c, _ = _client(monkeypatch, [])
    assert c.get("/conversations/nope").status_code == 404


def test_hidden_conversation_is_404(monkeypatch):
    c, _ = _client(monkeypatch, [_conv("c1", active=False)])
    assert c.get("/conversations/c1").status_code == 404


# ------------------------------------------------------------------ mutations

def test_create_returns_an_id_and_records_the_settings(monkeypatch):
    c, created = _client(monkeypatch, [])
    r = c.post("/conversations", json={"title": "Research", "mode": "research",
                                      "connectors": ["arxiv"]})
    assert r.status_code == 201
    assert r.json() == {"id": "newid"}
    uid, kw = created[0]
    assert uid == OWNER
    assert kw["mode"] == "research" and kw["connectors"] == ["arxiv"]


def test_rename(monkeypatch):
    convs = [_conv("c1")]
    c, _ = _client(monkeypatch, convs)
    r = c.patch("/conversations/c1", json={"title": "Renamed"})
    assert r.status_code == 200
    assert convs[0].title == "Renamed"


def test_rename_rejects_an_empty_or_oversized_title(monkeypatch):
    c, _ = _client(monkeypatch, [_conv("c1")])
    assert c.patch("/conversations/c1", json={"title": ""}).status_code == 422
    assert c.patch("/conversations/c1", json={"title": "x" * 201}).status_code == 422


def test_delete_hides_rather_than_removes(monkeypatch):
    convs = [_conv("c1")]
    c, _ = _client(monkeypatch, convs)
    assert c.delete("/conversations/c1").json() == {"deleted": "c1"}
    assert convs[0].active is False
    # and a second delete is a 404, not a second success
    assert c.delete("/conversations/c1").status_code == 404
