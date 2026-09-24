import fnmatch

from harness.policy.tiers import Decision, Tier


class ToolPolicy:
    """Tool name -> tier. Exact names first, then glob patterns (for tools
    that only exist after MCP discovery, e.g. ``gmail__*``), then the default."""

    def __init__(self, tiers: dict[str, Tier], default: Tier = Tier.SENSITIVE,
                 patterns: list[tuple[str, Tier]] | None = None):
        self._tiers = tiers
        self._default = default
        self._patterns = list(patterns or [])

    def tier_of(self, tool_name:str)->Tier:
        if tool_name in self._tiers:
            return self._tiers[tool_name]
        for pattern, tier in self._patterns:
            if fnmatch.fnmatch(tool_name, pattern):
                return tier
        return self._default

    def decide(self, tool_name:str)->Decision:
        tier = self.tier_of(tool_name)
        if tier in (Tier.SAFE, Tier.SENSITIVE):
            return Decision.ALLOW
        if tier in (Tier.DESTRUCTIVE, Tier.ELICIT):
            return Decision.NEEDS_APPROVAL
        return Decision.DENY
