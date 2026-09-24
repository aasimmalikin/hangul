"""Token vault: credentials are stored encrypted, the agent and MCP servers only
ever hold short-lived scoped grants, and every outbound call goes through the
proxy that injects the real credential server-side.

``current()`` is the running app's vault (set in the lifespan), mirroring
``mcp.manager.current()``; ``None`` means the vault is disabled."""

from harness.vault.vault import Vault, VaultError, VaultUnavailable

_current: Vault | None = None


def set_current(vault: Vault | None) -> None:
    global _current
    _current = vault


def current() -> Vault | None:
    return _current


__all__ = ["Vault", "VaultError", "VaultUnavailable", "current", "set_current"]
