"""The memory endpoints only ever show or forget the caller's own rows.

Runs against fakes for the db layer (no Postgres), like the other unit tests.
"""
from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from harness.api.auth import get_current_user
from harness.api.routes import memory as memory_route


def _row(id, user_id, content, active=True):
    return SimpleNamespace(
        id=id, user_id=user_id, kind="preference", content=content, active=active,
        created_at=datetime(2026, 9, 17, tzinfo=timezone.utc),
    )


def _client(monkeypatch, rows, user_id="7"):
    def list_active(uid):
        return [r for r in rows if r.user_id == int(uid) and r.active]

    def deactivate_memory(uid, mid):
        for r in rows:
            if r.id == mid and r.user_id == int(uid) and r.active:
                r.active = False
                return True
        return False

    monkeypatch.setattr(memory_route, "list_active", list_active)
    monkeypatch.setattr(memory_route, "deactivate_memory", deactivate_memory)

    app = FastAPI()
    app.include_router(memory_route.router)
    app.dependency_overrides[get_current_user] = lambda: {"user_id": user_id, "role": "user"}
    return TestClient(app)


def test_get_lists_only_the_callers_active_rows(monkeypatch):
    rows = [_row(1, 7, "likes tea"), _row(2, 8, "someone else"), _row(3, 7, "old", active=False)]
    r = _client(monkeypatch, rows).get("/memory")
    assert r.status_code == 200
    body = r.json()
    assert [m["id"] for m in body] == [1]
    assert body[0] == {"id": 1, "kind": "preference", "content": "likes tea", "created_at": "2026-09-17T00:00:00Z"}


def test_delete_own_row_then_404_on_repeat(monkeypatch):
    rows = [_row(1, 7, "likes tea")]
    c = _client(monkeypatch, rows)
    assert c.delete("/memory/1").json() == {"deleted": 1}
    assert rows[0].active is False
    assert c.delete("/memory/1").status_code == 404      # already inactive


def test_delete_someone_elses_row_is_404_and_leaves_it_alone(monkeypatch):
    rows = [_row(2, 8, "someone else")]
    r = _client(monkeypatch, rows).delete("/memory/2")
    assert r.status_code == 404
    assert rows[0].active is True


def test_delete_non_numeric_id_is_422(monkeypatch):
    assert _client(monkeypatch, []).delete("/memory/abc").status_code == 422
