"""The MCP client manager: config loading, connection lifecycle, tool
discovery + namespacing, invocation with lazy reconnect, and cleanup.
All against a fake client -- no subprocess is ever spawned."""

import asyncio
import os
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mcp import types

from harness.api.routes import health
from harness.mcp import manager as manager_mod
from harness.mcp.client import ConnectionState
from harness.mcp.config import ServerConfig, load_server_configs, server_config_from_dict
from harness.mcp.manager import MCPManager, render_result
from harness.tools.registry import ToolRegistry

# ------------------------------------------------------------------ fakes

def _tool(name, desc="", required=None):
    return SimpleNamespace(
        name=name, description=desc,
        inputSchema={"type": "object", "properties": {}, "required": required or []},
    )


class FakeClient:
    """Stands in for MCPClient: same attributes and coroutines, no I/O."""
    def __init__(self, config: ServerConfig, tools=None, fail_connect=False, fail_call=False):
        self.config = config
        self.state = ConnectionState.DISCONNECTED
        self.last_error = None
        self.connected_at = None
        self.tools = tools or []
        self.fail_connect = fail_connect
        self.fail_call = fail_call
        self.fail_close = False
        self.connects = 0
        self.closes = 0
        self.calls: list[tuple[str, dict]] = []
        self.result: types.CallToolResult | None = None

    @property
    def name(self):
        return self.config.name

    @property
    def connected(self):
        return self.state is ConnectionState.CONNECTED

    async def connect(self):
        self.connects += 1
        if self.fail_connect:
            self.state = ConnectionState.FAILED
            self.last_error = "RuntimeError: boom"
            raise RuntimeError("boom")
        self.state = ConnectionState.CONNECTED
        self.connected_at = 1.0

    async def aclose(self):
        self.closes += 1
        if self.state is not ConnectionState.FAILED:
            self.state = ConnectionState.DISCONNECTED
        if self.fail_close:
            raise RuntimeError("close exploded")

    async def list_tools(self):
        return list(self.tools)

    async def call_tool(self, name, arguments=None):
        self.calls.append((name, arguments or {}))
        if self.fail_call:
            self.state = ConnectionState.FAILED
            self.last_error = "ConnectionError: pipe closed"
            raise ConnectionError("pipe closed")
        if self.result is not None:
            return self.result
        return types.CallToolResult(content=[types.TextContent(type="text", text=f"{name}:{arguments}")])


def make_manager(specs: dict[str, dict]) -> tuple[MCPManager, dict[str, FakeClient]]:
    """specs: name -> FakeClient kwargs (tools, fail_connect, ...)."""
    fakes: dict[str, FakeClient] = {}

    def factory(cfg):
        fakes[cfg.name] = FakeClient(cfg, **specs[cfg.name])
        return fakes[cfg.name]

    configs = [ServerConfig(name=n, command="x") for n in specs]
    return MCPManager(configs, client_factory=factory), fakes


def run(coro):
    return asyncio.run(coro)


# ----------------------------------------------------------------- config

def test_load_yaml_roundtrip_and_env_expansion(tmp_path, monkeypatch):
    monkeypatch.setenv("MCP_TOKEN", "s3cret")
    f = tmp_path / "servers.yaml"
    f.write_text("""
servers:
  - name: fs
    transport: stdio
    command: npx
    args: ["-y", "pkg", "docs"]
    env: {HOME: "${HOME}"}
  - name: remote
    transport: streamable_http
    url: https://x.example/mcp
    headers: {Authorization: "Bearer ${MCP_TOKEN}"}
    call_timeout_s: 5
  - name: off
    transport: sse
    url: http://localhost:1/sse
    enabled: false
""")
    cfgs = load_server_configs(f)
    assert [c.name for c in cfgs] == ["fs", "remote"]           # disabled one dropped
    assert cfgs[0].args == ("-y", "pkg", "docs")
    assert cfgs[0].env == {"HOME": os.environ["HOME"]}
    assert cfgs[1].headers == {"Authorization": "Bearer s3cret"}
    assert cfgs[1].call_timeout_s == 5.0


def test_missing_or_empty_yaml_gives_default_filesystem_server(tmp_path):
    assert [c.name for c in load_server_configs(tmp_path / "nope.yaml")] == ["filesystem"]
    empty = tmp_path / "empty.yaml"
    empty.write_text("servers: []\n")
    assert [c.name for c in load_server_configs(empty)] == ["filesystem"]


@pytest.mark.parametrize("raw", [
    {"name": "a", "transport": "stdio"},                       # stdio without command
    {"name": "a", "transport": "sse"},                         # sse without url
    {"name": "a__b", "transport": "stdio", "command": "x"},    # separator in name
    {"name": "bad name", "transport": "stdio", "command": "x"},
    {"name": "a", "transport": "carrier-pigeon", "command": "x"},
    {"name": "a", "transport": "stdio", "command": "x", "call_timeout_s": 0},
])
def test_config_validation_errors(raw):
    with pytest.raises(ValueError):
        server_config_from_dict(raw)


def test_duplicate_server_names_rejected(tmp_path):
    f = tmp_path / "dup.yaml"
    f.write_text("servers:\n  - {name: a, command: x}\n  - {name: a, command: y}\n")
    with pytest.raises(ValueError, match="duplicate"):
        load_server_configs(f)
    with pytest.raises(ValueError, match="duplicate"):
        MCPManager([ServerConfig(name="a", command="x"), ServerConfig(name="a", command="y")])


# -------------------------------------------------------------- lifecycle

def test_connect_all_isolates_failures():
    mgr, _ = make_manager({
        "good": {"tools": [_tool("read_file")]},
        "bad": {"fail_connect": True},
    })
    errors = run(mgr.connect_all())
    assert errors["good"] is None and isinstance(errors["bad"], RuntimeError)
    by_name = {s.name: s for s in mgr.status()}
    assert by_name["good"].state == "connected" and by_name["good"].tool_count == 1
    assert by_name["bad"].state == "failed" and "boom" in by_name["bad"].last_error
    assert [t.name for t in mgr.tools()] == ["good__read_file"]


def test_aclose_closes_every_client_even_when_one_raises():
    mgr, fakes = make_manager({"a": {"tools": [_tool("t")]}, "b": {}, "c": {}})
    run(mgr.connect_all())
    fakes["b"].fail_close = True

    async def scenario():
        await mgr.aclose()
        await mgr.aclose()   # idempotent

    run(scenario())
    assert all(f.closes == 1 for f in fakes.values())
    assert mgr.closed and mgr.tools() == []
    assert run(mgr.call_tool("a__t", {})) == "[mcp error] manager closed"
    with pytest.raises(RuntimeError):
        run(mgr.connect_all())


def test_async_context_manager_connects_and_closes():
    mgr, fakes = make_manager({"a": {"tools": [_tool("t")]}})

    async def scenario():
        async with mgr as m:
            assert m.tools()[0].name == "a__t"
        assert mgr.closed

    run(scenario())
    assert fakes["a"].connects == 1 and fakes["a"].closes == 1


# --------------------------------------------------- discovery/namespacing

def test_same_tool_name_on_two_servers_is_namespaced_not_shadowed():
    mgr, _ = make_manager({
        "a": {"tools": [_tool("read_file", "reads")]},
        "b": {"tools": [_tool("read_file", "reads too")]},
    })
    run(mgr.connect_all())
    names = sorted(t.name for t in mgr.tools())
    assert names == ["a__read_file", "b__read_file"]
    assert mgr.tools("a")[0].description == "[a] reads"
    assert mgr.owner("b__read_file") == "b"
    assert mgr.alerts == []


def test_qualify_split_roundtrip():
    mgr = MCPManager()
    assert mgr.qualify("fs", "read_file") == "fs__read_file"
    assert mgr.split("fs__read_file") == ("fs", "read_file")
    assert mgr.split("fs__read__file") == ("fs", "read__file")   # first separator only
    for bad in ("nounderscore", "__x", "x__", ""):
        with pytest.raises(KeyError):
            mgr.split(bad)


def test_register_into_registry_and_rediscovery_replaces_stale_tools():
    mgr, fakes = make_manager({"a": {"tools": [_tool("old"), _tool("keep")]}})
    run(mgr.connect_all())
    reg = ToolRegistry()
    assert mgr.register_into(reg) == 2
    assert sorted(t.name for t in reg.list()) == ["a__keep", "a__old"]

    fakes["a"].tools = [_tool("keep"), _tool("new")]
    run(mgr.reconnect("a"))
    assert sorted(t.name for t in mgr.tools()) == ["a__keep", "a__new"]
    with pytest.raises(KeyError):
        mgr.owner("a__old")


def test_duplicate_tool_within_one_server_is_alerted():
    mgr, _ = make_manager({"a": {"tools": [_tool("x", "first"), _tool("x", "second")]}})
    run(mgr.connect_all())
    assert [t.description for t in mgr.tools()] == ["[a] first"]
    assert len(mgr.alerts) == 1 and "more than once" in mgr.alerts[0]


# ------------------------------------------------------------- invocation

def test_call_tool_routes_to_server_with_unqualified_name():
    mgr, fakes = make_manager({"a": {"tools": [_tool("read_file")]}, "b": {}})
    run(mgr.connect_all())
    out = run(mgr.call_tool("a__read_file", {"path": "x"}))
    assert out == "read_file:{'path': 'x'}"
    assert fakes["a"].calls == [("read_file", {"path": "x"})]
    assert fakes["b"].calls == []


def test_adapted_handler_goes_through_manager_and_defaults_path():
    mgr, fakes = make_manager({"a": {"tools": [_tool("list_directory", required=["path"])]}})
    run(mgr.connect_all())
    tool = mgr.tools()[0]
    run(tool.handler())
    assert fakes["a"].calls == [("list_directory", {"path": "."})]


def test_is_error_result_is_prefixed():
    mgr, fakes = make_manager({"a": {"tools": [_tool("t")]}})
    run(mgr.connect_all())
    fakes["a"].result = types.CallToolResult(
        content=[types.TextContent(type="text", text="no such file")], is_error=True,
    )
    assert run(mgr.call_tool("a__t", {})) == "[tool error] no such file"


def test_render_result_falls_back_to_structured_and_labels_binary():
    r = types.CallToolResult(content=[], structured_content={"n": 1})
    assert render_result(r) == '{"n": 1}'
    r = types.CallToolResult(content=[types.ImageContent(type="image", data="AA==", mimeType="image/png")])
    assert render_result(r) == "[image content]"


def test_failed_server_is_reconnected_once_on_next_call():
    mgr, fakes = make_manager({"a": {"tools": [_tool("t")]}})
    run(mgr.connect_all())
    fakes["a"].state = ConnectionState.FAILED
    out = run(mgr.call_tool("a__t", {"k": 1}))
    assert out == "t:{'k': 1}"
    assert fakes["a"].connects == 2 and fakes["a"].closes == 1


def test_reconnect_failure_returns_error_text():
    mgr, fakes = make_manager({"a": {"tools": [_tool("t")]}})
    run(mgr.connect_all())
    fakes["a"].state = ConnectionState.FAILED
    fakes["a"].fail_connect = True
    out = run(mgr.call_tool("a__t", {}))
    assert out == "[mcp error] server 'a' unavailable: RuntimeError: boom"
    assert fakes["a"].connects == 2      # exactly one retry, no loop


def test_transport_error_during_call_marks_failed_and_returns_text():
    mgr, fakes = make_manager({"a": {"tools": [_tool("t")]}})
    run(mgr.connect_all())
    fakes["a"].fail_call = True
    out = run(mgr.call_tool("a__t", {}))
    assert out.startswith("[mcp error] a.t failed: ConnectionError")
    assert mgr.status()[0].state == "failed"


def test_concurrent_calls_reconnect_only_once():
    mgr, fakes = make_manager({"a": {"tools": [_tool("t")]}})
    run(mgr.connect_all())
    fakes["a"].state = ConnectionState.FAILED

    async def scenario():
        return await asyncio.gather(*(mgr.call_tool("a__t", {}) for _ in range(5)))

    outs = run(scenario())
    assert all(o == "t:{}" for o in outs)
    assert fakes["a"].connects == 2


def test_unknown_names_are_errors_not_exceptions():
    mgr, _ = make_manager({"a": {}})
    run(mgr.connect_all())
    assert run(mgr.call_tool("zzz__t", {})) == "[mcp error] unknown server 'zzz'"
    assert run(mgr.call_tool("plain", {})).startswith("[mcp error]")


# ----------------------------------------------------------------- healthz

def test_healthz_reports_per_server_status():
    mgr, _ = make_manager({"good": {"tools": [_tool("t")]}, "bad": {"fail_connect": True}})
    run(mgr.connect_all())
    app = FastAPI()
    app.include_router(health.router)
    manager_mod.set_current(mgr)
    try:
        body = TestClient(app).get("/healthz").json()
    finally:
        manager_mod.set_current(None)
    assert body["status"] == "ok"
    by_name = {s["name"]: s for s in body["mcp"]}
    assert by_name["good"] == {"name": "good", "transport": "stdio", "state": "connected",
                               "tool_count": 1, "last_error": None, "connected_at": 1.0}
    assert by_name["bad"]["state"] == "failed" and "boom" in by_name["bad"]["last_error"]


def test_healthz_without_manager_is_still_ok():
    app = FastAPI()
    app.include_router(health.router)
    manager_mod.set_current(None)
    assert TestClient(app).get("/healthz").json() == {"status": "ok", "mcp": []}


def test_lenient_transport_accepts_jsonrpc_result_with_4xx_status():
    """Google's Workspace MCP servers answer tools/list with HTTP 403 + a valid
    result when some tools need scopes the token lacks. The shim turns that
    into a 200; real errors and JSON-RPC error replies are left alone."""
    import json

    import httpx

    from harness.mcp.client import LenientJsonRpcTransport

    def upstream(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        if body["method"] == "tools/list":
            # gzip-framed like a real server: the shim must drop the framing headers it cannot honour
            import gzip
            raw = json.dumps({"jsonrpc": "2.0", "id": body["id"], "result": {"tools": []}}).encode()
            return httpx.Response(403, content=gzip.compress(raw),
                                  headers={"content-type": "application/json", "content-encoding": "gzip"})
        if body["method"] == "bad":
            return httpx.Response(400, json={"jsonrpc": "2.0", "id": body["id"], "error": {"code": -32602, "message": "nope"}})
        if body["method"] == "html":
            return httpx.Response(503, text="<h1>down</h1>")
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": {}})

    client = httpx.AsyncClient(transport=LenientJsonRpcTransport(httpx.MockTransport(upstream)), base_url="https://x")

    async def scenario():
        r = await client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        assert r.status_code == 200 and r.json()["result"] == {"tools": []}
        r = await client.post("/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "bad"})
        assert r.status_code == 400 and "error" in r.json()
        r = await client.post("/mcp", json={"jsonrpc": "2.0", "id": 3, "method": "html"})
        assert r.status_code == 503 and "down" in r.text
        r = await client.post("/mcp", json={"jsonrpc": "2.0", "id": 4, "method": "initialize"})
        assert r.status_code == 200
        await client.aclose()
    run(scenario())
