"""Connectors: optional tool sources a user switches on per conversation
(the "+ → Connectors" menu), as opposed to the tools every run gets.

A connector is either *builtin* (tools implemented here, e.g. arXiv over its
public API) or *mcp* (an MCP server in servers.yaml tagged ``connector``,
whose namespaced tools are exposed only when the connector is on)."""

from harness.connectors.registry import available, tools_for, validate_keys

__all__ = ["available", "tools_for", "validate_keys"]
