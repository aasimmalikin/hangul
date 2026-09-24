"""Adapt MCP tool descriptors into the harness Tool shape.

Handlers do not hold a client: they call back into the manager by qualified
name, so reconnects and error translation happen in one place."""

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from harness.tools.base import Tool

if TYPE_CHECKING:
    from harness.mcp.manager import MCPManager


def tool_schema(mt: Any) -> dict:
    return getattr(mt, "input_schema", None) or getattr(mt, "inputSchema", None) or {}


def adapt_mcp_tool(manager: "MCPManager", server: str, mcp_tools: list) -> list[Tool]:
    tools: list[Tool] = []
    for mt in mcp_tools:
        schema = tool_schema(mt)
        required = list(schema.get("required", []) or [])
        qualified = manager.qualify(server, mt.name)

        def make_handler(name: str, required_fields: list) -> Callable[..., Awaitable[str]]:
            async def handler(**kwargs) -> str:
                # If the model omitted a required 'path', default it to "." (the
                # filesystem server's root). Prevents the empty-args retry loop.
                if "path" in required_fields and not kwargs.get("path"):
                    kwargs["path"] = "."
                return await manager.call_tool(name, kwargs)
            return handler

        tools.append(Tool(
            name=qualified,
            description=f"[{server}] {mt.description or ''}".rstrip(),
            parameter=schema,
            handler=make_handler(qualified, required),
        ))
    return tools
