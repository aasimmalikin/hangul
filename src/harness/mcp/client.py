"""One MCP server connection.

Owns the transport (subprocess for stdio, HTTP client for the others) and the
``ClientSession`` on top of it, keeps the session open so tools can be called
repeatedly, and tracks connection state so the manager can decide whether to
reconnect. Everything that can leak lives inside one ``AsyncExitStack``, so
``aclose()`` is the single teardown path."""

import asyncio
import json
import time
from contextlib import AsyncExitStack
from enum import Enum

import httpx
from mcp import ClientSession, StdioServerParameters, types
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client

from harness.logging import log
from harness.mcp.config import ServerConfig, has_vault_refs


class LenientJsonRpcTransport(httpx.AsyncBaseTransport):
    """Wraps an httpx transport: a non-2xx JSON response that parses as a
    JSON-RPC message carrying ``result`` is rewritten to 200. Errors, non-JSON
    bodies and JSON-RPC ``error`` replies pass through untouched."""

    def __init__(self, inner: httpx.AsyncBaseTransport) -> None:
        self._inner = inner

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        resp = await self._inner.handle_async_request(request)
        if resp.status_code < 400 or not resp.headers.get("content-type", "").lower().startswith("application/json"):
            return resp
        body = await resp.aread()          # decoded (decompressed) bytes
        await resp.aclose()
        try:
            msg = json.loads(body)
        except ValueError:
            msg = None
        # the body is re-attached already decoded, so the framing headers of the
        # original (gzip, length, chunking) must not travel with it
        headers = [(k, v) for k, v in resp.headers.raw
                   if k.lower() not in (b"content-encoding", b"content-length", b"transfer-encoding")]
        status = resp.status_code
        if isinstance(msg, dict) and msg.get("jsonrpc") == "2.0" and "result" in msg and "error" not in msg:
            log.info("MCP server answered a JSON-RPC result with a non-2xx status; accepting",
                     status=status, method=_method_of(request))
            status = 200
        return httpx.Response(status, headers=headers, content=body, request=request)

    async def aclose(self) -> None:
        await self._inner.aclose()


def _method_of(request: httpx.Request) -> str | None:
    try:
        return json.loads(request.content).get("method")
    except (ValueError, AttributeError):
        return None


class ConnectionState(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    FAILED = "failed"


class MCPClient:
    def __init__(self, config: ServerConfig, subject: str | None = None) -> None:
        self.config = config
        self.subject = subject            # set for a per-user session
        self.state = ConnectionState.DISCONNECTED
        self.last_error: str | None = None
        self.connected_at: float | None = None
        self.server_info: types.Implementation | None = None
        self._session: ClientSession | None = None
        self._task: asyncio.Task | None = None
        self._ready = asyncio.Event()
        self._close_requested = asyncio.Event()
        self._connect_error: Exception | None = None
        self._grants: list[str] = []      # vault grant tokens minted for this connection

    @property
    def name(self) -> str:
        return self.config.name

    @property
    def connected(self) -> bool:
        return self.state is ConnectionState.CONNECTED and self._session is not None

    # ------------------------------------------------------------ lifecycle

    async def _resolved_config(self) -> ServerConfig:
        """Swap "vault:<provider>" / "vault-proxy:<provider>" in env, headers
        and url for a fresh grant / the proxy URL. A new grant per connection
        means a restarted server never reuses an old token."""
        cfg = self.config
        from dataclasses import replace

        from harness.integrations.tokens import has_user_token_refs, substitute
        if self.subject is not None and (has_user_token_refs(cfg.headers) or has_user_token_refs(cfg.env)):
            # the third party's own token for this user (e.g. a Google access token)
            cfg = replace(cfg, headers=await substitute(cfg.headers, self.subject),
                          env=await substitute(cfg.env, self.subject))
        if not has_vault_refs(cfg):
            return cfg

        from harness.vault import current as current_vault
        vault = current_vault()
        if vault is None:
            raise ConnectionError(f"MCP server {cfg.name!r} references the vault but the vault is disabled")
        env, minted = await vault.resolve_refs(cfg.env)
        headers, minted2 = await vault.resolve_refs(cfg.headers)
        url_map, minted3 = await vault.resolve_refs({"url": cfg.url} if cfg.url else None)
        self._grants = minted + minted2 + minted3
        return replace(cfg, env=env, headers=headers, url=(url_map or {}).get("url", cfg.url))

    async def _revoke_grants(self) -> None:
        tokens, self._grants = self._grants, []
        if not tokens:
            return
        from harness.vault import current as current_vault
        vault = current_vault()
        if vault is not None:
            for t in tokens:
                await vault.revoke_grant(t)

    def _transport(self, cfg: ServerConfig):
        if cfg.transport == "stdio":
            return stdio_client(StdioServerParameters(
                command=cfg.command, args=list(cfg.args), env=cfg.env, cwd=cfg.cwd,
            ))
        if cfg.transport == "streamable_http":
            http = create_mcp_http_client(headers=cfg.headers) if cfg.headers else create_mcp_http_client()
            # Some servers (Google Workspace's "StatelessServer") put a 4xx status on a
            # reply whose body is a perfectly good JSON-RPC *result* (e.g. 403 on
            # tools/list when a few tools need scopes the token lacks). The SDK
            # treats any 4xx without a JSON-RPC error body as a failed session;
            # this transport lets such replies through as 200.
            http._transport = LenientJsonRpcTransport(http._transport)
            return streamable_http_client(cfg.url, http_client=http)
        if cfg.transport == "sse":
            return sse_client(cfg.url, headers=cfg.headers)
        raise ValueError(f"unknown transport {cfg.transport!r}")

    async def connect(self) -> None:
        """Open the transport and initialise the session.

        The transport and session context managers use anyio cancel scopes,
        which must be entered and exited by the *same* task. So the connection
        lives in its own owner task (``_run``) that enters the stack, signals
        ready, and waits for ``aclose()`` -- that way ``connect_all`` can fan
        out with ``gather`` and shutdown can happen from any task."""
        if self.connected:
            return
        await self.aclose()
        self.state = ConnectionState.CONNECTING
        self.last_error = None
        self._ready = asyncio.Event()
        self._close_requested = asyncio.Event()
        self._connect_error = None
        self._task = asyncio.create_task(self._run(), name=f"mcp:{self.name}")
        await self._ready.wait()
        if self._connect_error is not None:
            err, self._connect_error = self._connect_error, None
            self._task = None
            raise err

    async def _run(self) -> None:
        try:
            async with AsyncExitStack() as stack:
                async with asyncio.timeout(self.config.connect_timeout_s):
                    cfg = await self._resolved_config()
                    read, write = await stack.enter_async_context(self._transport(cfg))
                    session = await stack.enter_async_context(
                        ClientSession(read, write, read_timeout_seconds=self.config.call_timeout_s)
                    )
                    init = await session.initialize()
                self._session = session
                self.server_info = init.server_info
                self.state = ConnectionState.CONNECTED
                self.connected_at = time.time()
                log.info("MCP connected", server=self.name, transport=self.config.transport)
                self._ready.set()
                await self._close_requested.wait()
        except BaseException as e:
            if not self._ready.is_set():
                self._mark_failed(e)
                self._connect_error = e if isinstance(e, Exception) else ConnectionError(str(e))
            else:
                # the transport broke while tearing down (e.g. the child was
                # killed); nothing to do but note it
                log.warning("MCP close error", server=self.name, error=f"{type(e).__name__}: {e}")
            if isinstance(e, asyncio.CancelledError):
                raise
        finally:
            self._session = None
            await self._revoke_grants()
            self._ready.set()

    async def aclose(self) -> None:
        """Ask the owner task to leave the stack and wait for it. Idempotent."""
        task, self._task = self._task, None
        self._session = None
        if task is not None and not task.done():
            self._close_requested.set()
            try:
                await task
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 - must not block shutdown
                log.warning("MCP close error", server=self.name, error=str(e))
        if self.state is not ConnectionState.FAILED:
            self.state = ConnectionState.DISCONNECTED
        self.connected_at = None

    def _mark_failed(self, e: BaseException) -> None:
        self.state = ConnectionState.FAILED
        self.last_error = f"{type(e).__name__}: {e}" if str(e) else type(e).__name__

    def _require_session(self) -> ClientSession:
        if self._session is None or self.state is not ConnectionState.CONNECTED:
            raise ConnectionError(f"MCP server {self.name!r} is {self.state.value}")
        return self._session

    # ------------------------------------------------------------ protocol

    async def list_tools(self) -> list[types.Tool]:
        session = self._require_session()
        tools: list[types.Tool] = []
        cursor: str | None = None
        try:
            while True:
                params = types.PaginatedRequestParams(cursor=cursor) if cursor else None
                page = await session.list_tools(params=params)
                tools.extend(page.tools)
                cursor = page.next_cursor
                if not cursor:
                    return tools
        except Exception as e:
            self._mark_failed(e)
            raise

    async def call_tool(self, name: str, arguments: dict | None = None) -> types.CallToolResult:
        session = self._require_session()
        try:
            async with asyncio.timeout(self.config.call_timeout_s):
                result = await session.call_tool(name, arguments or {})
        except TimeoutError:
            # the session may be wedged; force a reconnect on the next call
            self._mark_failed(TimeoutError(f"call to {name} exceeded {self.config.call_timeout_s}s"))
            raise
        except Exception as e:
            self._mark_failed(e)
            raise
        if not isinstance(result, types.CallToolResult):
            raise TypeError(f"MCP server {self.name!r} returned {type(result).__name__} for {name}")
        return result

    async def ping(self) -> bool:
        if not self.connected:
            return False
        try:
            async with asyncio.timeout(self.config.call_timeout_s):
                await self._require_session().send_ping()
            return True
        except Exception as e:  # noqa: BLE001 - ping is a probe
            self._mark_failed(e)
            return False
