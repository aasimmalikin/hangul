"""Chat history endpoints only ever show, save or hide the caller's own
conversations. Runs against fakes (no Postgres, no embedding call)."""
from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from harness.api.auth import get_current_user
from harness.api.routes import episodes as ep_route

T = datetime(2026, 9, 17, tzinfo=timezone.utc)


def _row(id, user_id, thread_id, title, active=True, summary="Q: hello\nA: Hi there, here is   a long answer.\nQ: more"):
    return SimpleNamespace(id=id, user_id=user_id, thread_id=thread_id, title=title, summary=summary, active=active, created_at=T, updated_at=T)


def _client(monkeypatch, rows, user_id="7"):
    saved = []

    def list_episodes(uid):
        return [r for r in rows if r.user_id == int(uid) and r.active]

    def deactivate_episode(uid, eid):
        for r in rows:
            if r.id == eid and r.user_id == int(uid) and r.active:
                r.active = False
                return True
        return False

    async def store_episode(uid, thread_id, summary, title=""):
        saved.append((uid, thread_id, title, summary))
        return 99

    monkeypatch.setattr(ep_route, "list_episodes", list_episodes)
    monkeypatch.setattr(ep_route, "deactivate_episode", deactivate_episode)
    monkeypatch.setattr(ep_route, "store_episode", store_episode)
    app = FastAPI()
    app.include_router(ep_route.router)
    app.dependency_overrides[get_current_user] = lambda: {"user_id": user_id, "role": "user"}
    return TestClient(app), saved


def test_get_lists_only_the_callers_visible_chats(monkeypatch):
    rows = [_row(1, 7, "t1", "Draft a note"), _row(2, 8, "t2", "someone else"), _row(3, 7, "t3", "hidden", active=False)]
    c, _ = _client(monkeypatch, rows)
    r = c.get("/episodes")
    assert r.status_code == 200
    assert [e["title"] for e in r.json()] == ["Draft a note"]
    assert set(r.json()[0]) == {"id", "thread_id", "title", "preview", "summary", "created_at", "updated_at"}
    # preview is the first answer, whitespace collapsed, without the "A:" prefix
    assert r.json()[0]["preview"] == "Hi there, here is a long answer."


def test_preview_falls_back_to_the_question_and_truncates():
    from harness.api.routes.episodes import _preview
    assert _preview("Q: only a question") == "only a question"
    long = "A: " + "word " * 100
    p = _preview(long)
    assert len(p) <= 160 and p.endswith("…")
    assert _preview("") == ""


def test_post_saves_under_the_caller_and_returns_201(monkeypatch):
    c, saved = _client(monkeypatch, [])
    r = c.post("/episodes", json={"thread_id": "abc", "title": "Check the web", "summary": "Q: Check the web\nA: ..."})
    assert r.status_code == 201
    assert r.json() == {"id": 99, "thread_id": "abc"}
    assert saved == [("7", "abc", "Check the web", "Q: Check the web\nA: ...")]


def test_post_rejects_empty_or_oversized_bodies(monkeypatch):
    c, saved = _client(monkeypatch, [])
    assert c.post("/episodes", json={"thread_id": "", "title": "x", "summary": "y"}).status_code == 422
    assert c.post("/episodes", json={"thread_id": "a", "title": "x", "summary": "y" * 3000}).status_code == 422
    assert saved == []


def test_delete_own_then_404_on_repeat_and_foreign(monkeypatch):
    rows = [_row(1, 7, "t1", "mine"), _row(2, 8, "t2", "theirs")]
    c, _ = _client(monkeypatch, rows)
    assert c.delete("/episodes/1").json() == {"deleted": 1}
    assert rows[0].active is False
    assert c.delete("/episodes/1").status_code == 404
    assert c.delete("/episodes/2").status_code == 404
    assert rows[1].active is True
