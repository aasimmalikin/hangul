from collections.abc import Callable
from dataclasses import dataclass, field

from harness.policy.tiers import Tier
from harness.tools.base import Tool


@dataclass(frozen=True)
class Connector:
    key: str                    # what the request carries, e.g. "arxiv"
    label: str                  # menu label, e.g. "Research"
    description: str
    kind: str                   # "builtin" | "mcp"
    # builtin: a factory so tools are fresh per request (closure pattern);
    # a per-user builtin's factory takes the user id (e.g. Google over REST)
    tools: Callable[..., list[Tool]] | None = None
    # mcp: the server name(s) whose "<server>__*" tools this connector exposes
    # (a bundle groups several servers under one switch, e.g. Google Workspace)
    server: str | None = None
    servers: tuple[str, ...] = ()
    # per-user: each user connects their own session (OAuth), see MCPManager
    per_user: bool = False
    # how the UI lets the user connect it ("google" -> the Google OAuth flow)
    auth: str | None = None
    # policy tiers for the connector's tools (mcp tools default to SENSITIVE)
    tiers: dict[str, Tier] = field(default_factory=dict)
    # one paragraph the system prompt gets while the connector is on
    instruction: str = ""
    icon: str = "plug"

    def public(self) -> dict:
        return {"key": self.key, "label": self.label, "description": self.description,
                "kind": self.kind, "icon": self.icon, "per_user": self.per_user, "auth": self.auth,
                "servers": list(self.servers) or ([self.server] if self.server else [])}
