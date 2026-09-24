"""Server definitions for the MCP client manager.

The list of servers lives in ``servers.yaml`` next to this file. Each entry
picks a transport (stdio / streamable_http / sse) and the settings that
transport needs. ``${VAR}`` in string values is expanded from the environment
so secrets never have to be committed."""

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml

Transport = Literal["stdio", "streamable_http", "sse"]
TRANSPORTS: tuple[str, ...] = ("stdio", "streamable_http", "sse")

# a server name becomes the tool namespace prefix, so it must be a clean
# identifier and must not itself contain the separator
SEPARATOR = "__"
_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")

DEFAULT_CONFIG_PATH = Path(__file__).parent / "servers.yaml"

# "vault:<provider>" -> a short-lived grant token minted at connect time;
# "vault-proxy:<provider>" -> this API's /vault/proxy/<provider>/ base URL.
# Resolved by MCPClient via harness.vault, never here.
VAULT_REF = "vault:"
VAULT_PROXY_REF = "vault-proxy:"
_SECRET_KEY_RE = re.compile(r"token|secret|key|password|passwd|credential", re.IGNORECASE)
_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ServerConfig:
    name: str
    transport: Transport = "stdio"
    # stdio
    command: str | None = None
    args: tuple[str, ...] = ()
    env: dict[str, str] | None = None
    cwd: str | None = None
    # streamable_http / sse
    url: str | None = None
    headers: dict[str, str] | None = None
    # common
    enabled: bool = True
    connect_timeout_s: float = 30.0
    call_timeout_s: float = 60.0
    tags: tuple[str, ...] = field(default_factory=tuple)

    @property
    def per_user(self) -> bool:
        """Connected once per user (its headers carry ``user-token:`` refs),
        never as a shared process-level session."""
        return "per-user" in self.tags or any("user-token:" in v for v in (self.headers or {}).values())

    def tag(self, key: str) -> str | None:
        """Value of a ``key:value`` tag, e.g. ``bundle:google``."""
        return next((t.split(":", 1)[1] for t in self.tags if t.startswith(key + ":")), None)

    def validate(self) -> None:
        if not _NAME_RE.match(self.name):
            raise ValueError(f"MCP server name {self.name!r} must match {_NAME_RE.pattern}")
        if SEPARATOR in self.name:
            raise ValueError(f"MCP server name {self.name!r} must not contain {SEPARATOR!r}")
        if self.transport not in TRANSPORTS:
            raise ValueError(f"MCP server {self.name!r}: unknown transport {self.transport!r}")
        if self.transport == "stdio" and not self.command:
            raise ValueError(f"MCP server {self.name!r}: stdio transport needs 'command'")
        if self.transport in ("streamable_http", "sse") and not self.url:
            raise ValueError(f"MCP server {self.name!r}: {self.transport} transport needs 'url'")
        if self.connect_timeout_s <= 0 or self.call_timeout_s <= 0:
            raise ValueError(f"MCP server {self.name!r}: timeouts must be positive")


# what the harness ran before servers.yaml existed; used when the file is
# missing or empty so a fresh checkout behaves the same
DEFAULT_SERVERS: tuple[ServerConfig, ...] = (
    ServerConfig(
        name="filesystem",
        transport="stdio",
        command="npx",
        args=("-y", "@modelcontextprotocol/server-filesystem", "docs", "data/sessions"),
    ),
)


def _expand(value: Any) -> Any:
    if isinstance(value, str):
        return os.path.expandvars(value)
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_expand(v) for v in value]
    return value


def _warn_raw_secrets(name: str, raw: dict[str, Any]) -> None:
    """A secret-looking key whose value is a raw ${VAR} hands the real token
    to the server process. Point at the vault instead."""
    for section in ("env", "headers"):
        for k, v in (raw.get(section) or {}).items():
            if isinstance(v, str) and "${" in v and _SECRET_KEY_RE.search(str(k)):
                _log.warning("MCP server %r passes a raw secret in %s.%s; consider \"vault:<provider>\" "
                             "so the process only ever holds a short-lived grant", name, section, k)


def has_vault_refs(cfg: "ServerConfig") -> bool:
    for m in (cfg.env or {}, cfg.headers or {}):
        if any(VAULT_REF in v or VAULT_PROXY_REF in v for v in m.values()):
            return True
    return bool(cfg.url and (VAULT_REF in cfg.url or VAULT_PROXY_REF in cfg.url))


def server_config_from_dict(raw: dict[str, Any]) -> ServerConfig:
    if not isinstance(raw, dict) or "name" not in raw:
        raise ValueError(f"MCP server entry must be a mapping with a 'name': {raw!r}")
    _warn_raw_secrets(str(raw.get("name")), raw)
    raw = _expand(raw)
    cfg = ServerConfig(
        name=str(raw["name"]),
        transport=raw.get("transport", "stdio"),
        command=raw.get("command"),
        args=tuple(str(a) for a in raw.get("args", []) or []),
        env={str(k): str(v) for k, v in (raw.get("env") or {}).items()} or None,
        cwd=raw.get("cwd"),
        url=raw.get("url"),
        headers={str(k): str(v) for k, v in (raw.get("headers") or {}).items()} or None,
        enabled=bool(raw.get("enabled", True)),
        connect_timeout_s=float(raw.get("connect_timeout_s", 30.0)),
        call_timeout_s=float(raw.get("call_timeout_s", 60.0)),
        tags=tuple(str(t) for t in raw.get("tags", []) or []),
    )
    cfg.validate()
    return cfg


def load_server_configs(path: Path | str = DEFAULT_CONFIG_PATH) -> list[ServerConfig]:
    """Read ``servers.yaml``. Missing or empty file -> DEFAULT_SERVERS.

    Disabled entries are dropped. Duplicate names are an error because the
    name is the tool namespace."""
    path = Path(path)
    if not path.exists():
        return list(DEFAULT_SERVERS)
    data = yaml.safe_load(path.read_text()) or {}
    entries = data.get("servers") if isinstance(data, dict) else None
    if not entries:
        return list(DEFAULT_SERVERS)

    configs: list[ServerConfig] = []
    seen: set[str] = set()
    for raw in entries:
        cfg = server_config_from_dict(raw)
        if cfg.name in seen:
            raise ValueError(f"duplicate MCP server name {cfg.name!r} in {path}")
        seen.add(cfg.name)
        if cfg.enabled:
            configs.append(cfg)
    return configs
