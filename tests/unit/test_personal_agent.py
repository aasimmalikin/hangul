"""Personal-agent features: personalisation, scheduled tasks, the Google
Workspace bundle (per-user MCP sessions + OAuth token source), research mode."""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from harness.api.auth import get_current_user
from harness.api.routes import ask as ask_route
from harness.api.routes import settings as settings_route
from harness.connectors import registry as creg
from harness.connectors.base import Connector
from harness.db import tasks as tasks_db
from harness.db.settings import Settings, prompt_block
from harness.integrations import google_oauth as go
from harness.integrations.tokens import substitute
from harness.mcp.config import ServerConfig
from harness.mcp.manager import MCPManager
from harness.policy.policy import ToolPolicy
from harness.policy.tiers import Tier
from harness.vault.redact import redactor


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------- personalisation

def test_prompt_block_includes_name_local_time_tone_and_instructions():
    st = Settings(display_name="Aasim", instructions="Always answer in bullet points.", tone="concise",
                  timezone="Asia/Kolkata", language="en")
    block = prompt_block(st, now=datetime(2026, 9, 18, 12, 0, tzinfo=UTC))
    assert "Name: Aasim" in block and "Asia/Kolkata" in block and "17:30" in block
    assert "Be brief" in block and "bullet points" in block and "unless they conflict with the rules above" in block
    assert prompt_block(Settings()).startswith("=== ABOUT THE USER ===")


def test_settings_routes_validate(monkeypatch):
    saved = {}
    monkeypatch.setattr(settings_route, "get_settings", lambda uid: Settings(**saved) if saved else Settings())

    def fake_save(uid, values):
        from harness.db.settings import TONES, valid_timezone
        if values.tone not in TONES or not valid_timezone(values.timezone):
            raise ValueError("bad")
        saved.update(values.as_dict())
        return values
    monkeypatch.setattr(settings_route, "save_settings", fake_save)
    app = FastAPI()
    app.include_router(settings_route.router)
    app.dependency_overrides[get_current_user] = lambda: {"user_id": "7", "role": "user"}
    c = TestClient(app)
    assert c.get("/settings").json()["tone"] == "balanced"
    assert c.put("/settings", json={"display_name": "A", "timezone": "Europe/London", "tone": "detailed"}).status_code == 200
    assert c.get("/settings").json()["timezone"] == "Europe/London"
    assert c.put("/settings", json={"timezone": "Mars/Olympus"}).status_code == 422
    assert c.put("/settings", json={"tone": "shouty"}).status_code == 422


def test_research_mode_adds_arxiv_and_instruction_and_doubles_budget():
    req = ask_route.AskRequest(question="q", mode="research")
    assert req.mode == "research"
    with pytest.raises(ValueError):
        ask_route.AskRequest(question="q", mode="turbo")
    assert "DEEP RESEARCH MODE" in ask_route.RESEARCH_INSTRUCTION and "Sources" in ask_route.RESEARCH_INSTRUCTION


# ---------------------------------------------------------- scheduled tasks

def test_next_run_interval_and_daily_in_user_timezone():
    now = datetime(2026, 9, 18, 12, 0, tzinfo=UTC)
    assert tasks_db.compute_next_run(30, None, "UTC", after=now) == datetime(2026, 9, 18, 12, 30, tzinfo=UTC)
    assert tasks_db.compute_next_run(5, None, "UTC", after=now) == datetime(2026, 9, 18, 12, 15, tzinfo=UTC)  # floor 15
    # 09:00 Kolkata is 03:30 UTC -> already passed today at 12:00 UTC -> tomorrow
    nxt = tasks_db.compute_next_run(None, "09:00", "Asia/Kolkata", after=now)
    assert nxt == datetime(2026, 9, 19, 3, 30, tzinfo=UTC)
    nxt = tasks_db.compute_next_run(None, "20:00", "Asia/Kolkata", after=now)
    assert nxt == datetime(2026, 9, 18, 14, 30, tzinfo=UTC)


def test_task_routes_with_fake_store(monkeypatch):
    rows = {}
    seq = {"n": 0}

    def create(uid, **kw):
        if not (kw["every_minutes"] or kw["daily_at"]):
            raise ValueError("a schedule needs every_minutes or daily_at")
        seq["n"] += 1
        t = tasks_db.Task(id=seq["n"], user_id=int(uid), title=kw["title"], question=kw["question"],
                          every_minutes=kw["every_minutes"], daily_at=kw["daily_at"], connectors=kw["connectors"],
                          mode=kw["mode"], enabled=True, next_run_at=None, last_run_at=None, last_status="never",
                          last_run_id=None, last_answer="", created_at=None)
        rows[t.id] = t
        return t
    monkeypatch.setattr(settings_route.tasks_db, "create_task", create)
    monkeypatch.setattr(settings_route.tasks_db, "list_tasks", lambda uid: [t for t in rows.values() if t.user_id == int(uid)])
    monkeypatch.setattr(settings_route.tasks_db, "delete_task", lambda uid, tid: rows.pop(tid, None) is not None if tid in rows and rows[tid].user_id == int(uid) else False)
    monkeypatch.setattr(settings_route, "get_settings", lambda uid: Settings())
    app = FastAPI()
    app.include_router(settings_route.router)
    app.dependency_overrides[get_current_user] = lambda: {"user_id": "7", "role": "user"}
    c = TestClient(app)
    r = c.post("/tasks", json={"title": "Morning brief", "question": "Summarise my inbox", "daily_at": "08:00", "connectors": ["google"]})
    assert r.status_code == 201 and r.json()["connectors"] == ["google"]
    assert c.post("/tasks", json={"title": "x", "question": "y"}).status_code == 422                  # no schedule
    assert c.post("/tasks", json={"title": "x", "question": "y", "every_minutes": 5}).status_code == 422   # below floor
    assert c.post("/tasks", json={"title": "x", "question": "y", "every_minutes": 60, "connectors": ["nope"]}).status_code == 422
    assert [t["title"] for t in c.get("/tasks").json()] == ["Morning brief"]
    assert c.delete("/tasks/1").json() == {"deleted": 1}
    assert c.delete("/tasks/1").status_code == 404


# ------------------------------------------------- google oauth + bundle

def test_google_token_source_refreshes_and_caches(monkeypatch):
    monkeypatch.setenv("AUTH_GOOGLE_ID", "cid")
    monkeypatch.setenv("AUTH_GOOGLE_SECRET", "csecret")
    calls = []

    def handler(req: httpx.Request):
        calls.append(dict(httpx.QueryParams(req.content.decode())))
        return httpx.Response(200, json={"access_token": "ya29.fresh-token-value-000", "expires_in": 3600})
    src = go.GoogleTokenSource(http=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    grant = go.GoogleGrant(refresh_token="1//rt", scopes=set(go.WORKSPACE_SCOPES["gmail"]) | set(go.WORKSPACE_SCOPES["calendar"]))
    monkeypatch.setattr(go, "_load_grant", lambda uid: grant if uid == "7" else None)
    go.set_google_tokens(src)          # what user-token: refs resolve through

    async def scenario():
        assert (await src.status("7")) == {"connected": True, "products": ["gmail", "calendar"]}
        assert (await src.status("8"))["connected"] is False
        tok = await src.access_token("7", product="gmail")
        assert tok == "ya29.fresh-token-value-000" and calls[0]["grant_type"] == "refresh_token"
        assert await src.access_token("7") == tok and len(calls) == 1          # cached
        assert redactor.scrub_text(tok) != tok                                 # never logged raw
        with pytest.raises(go.GoogleNotConnected, match="drive scopes"):
            await src.access_token("7", product="drive")
        with pytest.raises(go.GoogleNotConnected, match="not connected"):
            await src.access_token("8")
        headers = await substitute({"Authorization": "Bearer user-token:google:gmail", "X": "plain"}, "7")
        assert headers == {"Authorization": f"Bearer {tok}", "X": "plain"}
    try:
        run(scenario())
    finally:
        go.set_google_tokens(None)
        redactor.forget("ya29.fresh-token-value-000")


def test_bundle_connector_from_servers_yaml_and_pattern_tiers(tmp_path):
    # the MCP bundle (disabled by default) still parses into one connector when enabled
    import harness.connectors.registry as r
    yaml_text = """servers:
  - {name: gmail, transport: streamable_http, url: https://g/mcp, headers: {Authorization: "Bearer user-token:google:gmail"}, tags: ["connector", "per-user", "bundle:gsuite", "label:G Suite"]}
  - {name: calendar, transport: streamable_http, url: https://c/mcp, headers: {Authorization: "Bearer user-token:google:calendar"}, tags: ["connector", "per-user", "bundle:gsuite"]}
"""
    f = tmp_path / "s.yaml"; f.write_text(yaml_text)
    import harness.mcp.config as mc
    orig = mc.load_server_configs
    mc.load_server_configs = lambda path=f: orig(path)
    try:
        cons = r.all_connectors()
    finally:
        mc.load_server_configs = orig
    g = cons["gsuite"]
    assert g.kind == "mcp" and g.per_user and g.servers == ("gmail", "calendar") and g.label == "G Suite"
    assert cons["google"].kind == "builtin"          # the REST connector is the default "google"
    pol = ask_route._policy
    assert pol.decide("gmail__send_message").value == "needs_approval"
    assert pol.decide("gmail__create_draft").value == "needs_approval" and pol.decide("docs__append_text").value == "needs_approval"
    assert pol.decide("gmail__search_messages").value == "allow"
    assert pol.decide("calendar__create_event").value == "needs_approval"
    assert pol.decide("drive__list_files").value == "allow"
    assert ToolPolicy(tiers={}, patterns=[("x__*", Tier.DENIED)]).decide("x__y").value == "deny"


def test_per_user_mcp_sessions_and_bundle_tools():
    """Two users get separate sessions on a per-user server; tools_for binds
    each user's tools to their own session; prepare() reports a user who
    cannot connect without failing the others."""
    from harness.mcp.client import ConnectionState

    class FakeUserClient:
        instances: list = []  # noqa: RUF012
        def __init__(self, cfg, subject=None):
            self.config, self.subject = cfg, subject
            self.state = ConnectionState.DISCONNECTED
            self.last_error = None; self.connected_at = None; self.calls = []
            FakeUserClient.instances.append(self)
        @property
        def connected(self): return self.state is ConnectionState.CONNECTED
        async def connect(self):
            if self.subject == "bad":
                raise RuntimeError("Google Workspace is not connected for this account")
            self.state = ConnectionState.CONNECTED
        async def aclose(self): self.state = ConnectionState.DISCONNECTED
        async def list_tools(self):
            return [SimpleNamespace(name="search_messages", description="", inputSchema={"type": "object", "properties": {}})]
        async def call_tool(self, name, arguments=None):
            from mcp import types
            self.calls.append((name, arguments))
            return types.CallToolResult(content=[types.TextContent(type="text", text=f"{self.subject}:{name}")])

    cfg = ServerConfig(name="gmail", transport="streamable_http", url="https://x/mcp",
                       headers={"Authorization": "Bearer user-token:google:gmail"}, tags=("connector", "per-user", "bundle:google"))
    mgr = MCPManager([cfg], client_factory=FakeUserClient)

    async def scenario():
        assert await mgr.connect_all() == {}                 # per-user servers are not connected at boot
        assert mgr.is_per_user("gmail")
        a = await mgr.ensure_user_session("gmail", "alice")
        b = await mgr.ensure_user_session("gmail", "bob")
        assert a is not b and a.subject == "alice" and [t.name for t in mgr.tools("gmail")] == ["gmail__search_messages"]
        assert await mgr.ensure_user_session("gmail", "alice") is a
        out = await mgr.call_tool("gmail__search_messages", {"q": "x"}, subject="bob")
        assert out == "bob:search_messages" and b.calls == [("search_messages", {"q": "x"})]
        assert (await mgr.call_tool("gmail__search_messages", {})).startswith("[mcp error] gmail needs a signed-in user")
        assert "not connected" in await mgr.call_tool("gmail__search_messages", {}, subject="bad")
        tools = mgr.tools_for_subject("gmail", "alice")
        assert await tools[0].handler(q="y") == "alice:search_messages"
        assert len(mgr.user_sessions()) == 2
        # idle reaping closes sessions nobody used
        mgr.user_idle_s = 0
        await mgr._reap_idle()
        assert mgr.user_sessions() == []
        # prepare() through the connector registry
        from harness.mcp import manager as mm
        mm.set_current(mgr)
        try:
            google = Connector(key="google", label="G", description="", kind="mcp", servers=("gmail",), per_user=True)
            import harness.connectors.registry as r
            orig = r.all_connectors
            r.all_connectors = lambda: {"google": google}
            try:
                assert await creg.prepare(["google"], "alice") == []
                problems = await creg.prepare(["google"], "bad")
                assert problems and "not connected" in problems[0]
                tools, _note, _ = creg.tools_for(["google"], [], user_id="alice", manager=mgr)
                assert [t.name for t in tools] == ["gmail__search_messages"]
                assert creg.tools_for(["google"], [], user_id=None, manager=mgr)[0] == []
            finally:
                r.all_connectors = orig
        finally:
            mm.set_current(None)
        await mgr.aclose()
    run(scenario())
