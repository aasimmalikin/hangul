"""Manage connections to many MCP servers as one tool source.

Responsibilities:
- lifecycle: connect every configured server (in parallel, failures isolated),
  reconnect a dead one lazily on its next tool call, close everything once
- discovery + aggregation: list each server's tools and keep them per server
- namespacing: every tool is exposed as ``<server>__<tool>`` so servers can
  never collide and a tool name always says where it runs
- invocation: ``call_tool(qualified, args)`` routes to the right client and
  turns transport / tool errors into strings the model can read
- cleanup: ``aclose()`` tears down all clients even if some fail
"""

import asyncio
import inspect
import json
import time
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from typing import Self

from mcp import types

from harness.logging import log
from harness.mcp.adapter import adapt_mcp_tool
from harness.mcp.client import MCPClient
from harness.mcp.config import SEPARATOR, ServerConfig
from harness.tools.base import Tool
from harness.tools.registry import ToolRegistry


@dataclass
class ServerStatus:
    name: str
    transport: str
    state: str
    tool_count: int
    last_error: str | None
    connected_at: float | None

    def as_dict(self) -> dict:
        return asdict(self)


class MCPManager:
    def __init__(
        self,
        configs: Iterable[ServerConfig] = (),
        *,
        separator: str = SEPARATOR,
        client_factory: Callable[[ServerConfig], MCPClient] = MCPClient,
    ) -> None:
        self._sep = separator
        self._factory = client_factory
        self._configs: dict[str, ServerConfig] = {}
        self._clients: dict[str, MCPClient] = {}
        self._tools: dict[str, dict[str, Tool]] = {}   # server -> qualified -> Tool
        self._owner: dict[str, str] = {}               # qualified -> server
        self._alerts: list[str] = []
        self._locks: dict[str, asyncio.Lock] = {}
        self._closed = False
        # per-user sessions for servers whose auth is the user's own token
        self._user_clients: dict[tuple[str, str], MCPClient] = {}
        self._user_last_used: dict[tuple[str, str], float] = {}
        self.user_idle_s = 30 * 60
        for cfg in configs:
            self.add(cfg)

    # ---------------------------------------------------------------- setup

    def add(self, cfg: ServerConfig) -> None:
        """Register a server definition. Connect with connect()/connect_all()."""
        cfg.validate()
        if self._sep in cfg.name:
            raise ValueError(f"server name {cfg.name!r} must not contain {self._sep!r}")
        if cfg.name in self._configs:
            raise ValueError(f"duplicate MCP server {cfg.name!r}")
        self._configs[cfg.name] = cfg
        self._clients[cfg.name] = self._factory(cfg)
        self._tools[cfg.name] = {}
        self._locks[cfg.name] = asyncio.Lock()

    @property
    def servers(self) -> list[str]:
        return list(self._configs)

    def client(self, name: str) -> MCPClient:
        if name not in self._clients:
            raise KeyError(f"unknown MCP server {name!r}")
        return self._clients[name]

    # ------------------------------------------------------------ lifecycle

    async def connect(self, name: str) -> None:
        """Connect one server and discover its tools. Raises on failure (the
        client is left in FAILED with last_error set)."""
        self._check_open()
        client = self.client(name)
        await client.connect()
        await self.discover(name)

    async def connect_all(self) -> dict[str, Exception | None]:
        """Connect every server in parallel. Never raises: a server that fails
        is logged, marked FAILED, and reported in the returned map."""
        self._check_open()

        async def one(name: str) -> Exception | None:
            try:
                await self.connect(name)
                return None
            except Exception as e:  # noqa: BLE001 - isolate per-server failures
                log.warning("MCP connect failed", server=name, error=self._clients[name].last_error or str(e))
                return e

        names = [n for n in self._clients if not self._configs[n].per_user]
        results = await asyncio.gather(*(one(n) for n in names))
        return dict(zip(names, results))

    async def disconnect(self, name: str) -> None:
        client = self.client(name)
        await client.aclose()
        self._forget_tools(name)

    async def reconnect(self, name: str) -> None:
        await self.disconnect(name)
        await self.connect(name)

    async def aclose(self) -> None:
        """Close every client, even if some raise. Idempotent."""
        if self._closed:
            return
        self._closed = True
        for name, client in self._clients.items():
            try:
                await client.aclose()
            except Exception as e:  # noqa: BLE001 - keep closing the rest
                log.warning("MCP close failed", server=name, error=str(e))
            self._forget_tools(name)
        for key, client in list(self._user_clients.items()):
            try:
                await client.aclose()
            except Exception as e:  # noqa: BLE001
                log.warning("MCP user session close failed", server=key[0], error=str(e))
        self._user_clients.clear()
        log.info("MCP manager closed", servers=list(self._clients))

    async def __aenter__(self) -> Self:
        await self.connect_all()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.aclose()

    def _check_open(self) -> None:
        if self._closed:
            raise RuntimeError("MCPManager is closed")

    # ------------------------------------------------- discovery/aggregation

    async def discover(self, name: str) -> list[Tool]:
        """(Re)list a server's tools, replacing whatever it exposed before."""
        client = self.client(name)
        raw = await client.list_tools()
        return self._store_discovered(name, adapt_mcp_tool(self, name, raw))

    def _store_discovered(self, name: str, adapted: list[Tool]) -> list[Tool]:
        self._forget_tools(name)
        kept: dict[str, Tool] = {}
        for tool in adapted:
            owner = self._owner.get(tool.name)
            if owner is not None and owner != name:
                # cannot happen with distinct prefixes, but a custom separator
                # or a server that returns pre-namespaced names could do it
                self._alert(f"tool {tool.name!r} from server {name!r} shadowed by server {owner!r}")
                continue
            if tool.name in kept:
                self._alert(f"server {name!r} lists tool {tool.name!r} more than once; keeping the first")
                continue
            kept[tool.name] = tool
            self._owner[tool.name] = name
        self._tools[name] = kept
        log.info("MCP tools discovered", server=name, count=len(kept), tools=list(kept))
        return list(kept.values())

    def tools(self, server: str | None = None) -> list[Tool]:
        if server is not None:
            return list(self._tools.get(server, {}).values())
        return [t for per in self._tools.values() for t in per.values()]

    def register_into(self, registry: ToolRegistry, server: str | None = None) -> int:
        tools = self.tools(server)
        for t in tools:
            registry.registry(t)
        return len(tools)

    def _forget_tools(self, name: str) -> None:
        for qualified in self._tools.get(name, {}):
            if self._owner.get(qualified) == name:
                del self._owner[qualified]
        self._tools[name] = {}

    def _alert(self, msg: str) -> None:
        self._alerts.append(msg)
        log.warning("MCP shadowing", alert=msg)

    @property
    def alerts(self) -> list[str]:
        return list(self._alerts)

    # ----------------------------------------------------------- namespacing

    def qualify(self, server: str, tool: str) -> str:
        return f"{server}{self._sep}{tool}"

    def split(self, qualified: str) -> tuple[str, str]:
        server, sep, tool = qualified.partition(self._sep)
        if not sep or not server or not tool:
            raise KeyError(f"{qualified!r} is not a namespaced MCP tool name")
        return server, tool

    def owner(self, qualified: str) -> str:
        """Which server currently exposes this tool (KeyError if none does)."""
        if qualified not in self._owner:
            raise KeyError(f"no MCP server exposes {qualified!r}")
        return self._owner[qualified]

    # ------------------------------------------------------------ invocation

    async def call_tool(self, qualified: str, arguments: dict | None = None, *, subject: str | None = None) -> str:
        """Invoke a namespaced tool. Never raises: errors come back as text so
        the agent loop can hand them to the model like any tool output.
        ``subject`` selects a per-user session for per-user servers."""
        if self._closed:
            return "[mcp error] manager closed"
        try:
            server, tool = self.split(qualified)
        except KeyError as e:
            return f"[mcp error] {e.args[0]}"
        if self.is_per_user(server):
            if subject is None:
                return f"[mcp error] {server} needs a signed-in user"
            try:
                client = await self.ensure_user_session(server, subject)
            except Exception as e:  # noqa: BLE001 - reported as text
                return f"[mcp error] {server} unavailable for this user: {e}"
            try:
                result = await client.call_tool(tool, arguments or {})
            except Exception as e:  # noqa: BLE001
                log.warning("MCP user call failed", server=server, tool=tool, error=str(e))
                return f"[mcp error] {server}.{tool} failed: {client.last_error or e}"
            return render_result(result)
        client = self._clients.get(server)
        if client is None:
            return f"[mcp error] unknown server {server!r}"

        if not client.connected:
            async with self._locks[server]:
                if not client.connected:  # someone else may have reconnected
                    try:
                        log.info("MCP reconnecting", server=server, state=client.state.value)
                        await self.reconnect(server)
                    except Exception:  # noqa: BLE001 - reported as text
                        return f"[mcp error] server {server!r} unavailable: {client.last_error}"

        try:
            result = await client.call_tool(tool, arguments or {})
        except Exception as e:  # noqa: BLE001 - reported as text
            log.warning("MCP call failed", server=server, tool=tool, error=str(e))
            return f"[mcp error] {server}.{tool} failed: {client.last_error or e}"
        return render_result(result)

    # ------------------------------------------------------ per-user sessions

    def is_per_user(self, name: str) -> bool:
        return name in self._configs and self._configs[name].per_user

    async def ensure_user_session(self, name: str, subject: str) -> MCPClient:
        """Connect (once) this user's own session to a per-user server and make
        sure its tools are discovered. Idle sessions are reaped opportunistically."""
        self._check_open()
        cfg = self._configs[name]
        if not cfg.per_user:
            raise ValueError(f"server {name!r} is not per-user")
        await self._reap_idle()
        key = (name, subject)
        client = self._user_clients.get(key)
        if client is None:
            client = self._factory(cfg, subject) if _accepts_subject(self._factory) else self._factory(cfg)
            client.subject = subject
            self._user_clients[key] = client
        self._user_last_used[key] = time.time()
        if not client.connected:
            try:
                await client.connect()
            except Exception:
                # no dead session lingers for this user; the next call retries from scratch
                self._user_clients.pop(key, None)
                self._user_last_used.pop(key, None)
                raise
            if not self._tools.get(name):
                # tool schemas are the same for every user; discover through the first session
                raw = await client.list_tools()
                self._store_discovered(name, adapt_mcp_tool(self, name, raw))
        return client

    def tools_for_subject(self, name: str, subject: str) -> list[Tool]:
        """This server's tools bound to one user's session."""
        from harness.tools.base import Tool as _Tool
        out = []
        for t in self._tools.get(name, {}).values():
            qualified = t.name

            def make(q):
                async def handler(**kw):
                    return await self.call_tool(q, kw, subject=subject)
                return handler
            out.append(_Tool(name=t.name, description=t.description, parameter=t.parameter, handler=make(qualified)))
        return out

    async def _reap_idle(self) -> None:
        now = time.time()
        for key in [k for k, t in self._user_last_used.items() if now - t > self.user_idle_s]:
            client = self._user_clients.pop(key, None)
            self._user_last_used.pop(key, None)
            if client is not None:
                await client.aclose()
                log.info("MCP user session reaped", server=key[0])

    def user_sessions(self) -> list[dict]:
        return [{"server": k[0], "subject": k[1], "state": c.state.value, "last_used": self._user_last_used.get(k)}
                for k, c in self._user_clients.items()]

    # ---------------------------------------------------------------- status

    def status(self) -> list[ServerStatus]:
        out = []
        for name, client in self._clients.items():
            out.append(ServerStatus(
                name=name,
                transport=self._configs[name].transport,
                state=client.state.value,
                tool_count=len(self._tools.get(name, {})),
                last_error=client.last_error,
                connected_at=client.connected_at,
            ))
        return out

    @property
    def closed(self) -> bool:
        return self._closed


def render_result(result: types.CallToolResult) -> str:
    """Flatten a CallToolResult into the single string the loop expects."""
    parts: list[str] = []
    for block in result.content or []:
        text = getattr(block, "text", None)
        if text is not None:
            parts.append(text)
        else:
            parts.append(f"[{getattr(block, 'type', type(block).__name__)} content]")
    text = "\n".join(parts)
    if not text and result.structured_content:
        text = json.dumps(result.structured_content)
    if result.is_error:
        return f"[tool error] {text or 'tool reported an error'}"
    return text


# The running app's manager, so routes (e.g. /healthz) can read status without
# importing app.py. Mirrors the module-level _registry in routes/ask.py.
_current: MCPManager | None = None


def set_current(manager: MCPManager | None) -> None:
    global _current
    _current = manager


def current() -> MCPManager | None:
    return _current


def _accepts_subject(factory) -> bool:
    try:
        return "subject" in inspect.signature(factory).parameters
    except (TypeError, ValueError):
        return False
