import asyncio

from harness.logging import log
from harness.policy.audit import AuditLog
from harness.policy.policy import ToolPolicy
from harness.policy.tiers import Decision
from harness.tools.base import Tool, ToolResult
from harness.tools.dispatch import dispatch

# a handler that reports a failure as text still returns ok=True
_FAILED = ("error", "[tool error]", "[mcp error]", "blocked", "could not", "failed", "invalid arguments",
           "vault_", "denied")


async def guarded_dispatch(tool: Tool, args: dict, policy: ToolPolicy, audit: AuditLog, approved: bool = False)->ToolResult:
    decision = policy.decide(tool.name)
    tier = policy.tier_of(tool.name)
    audit.record(tool = tool.name, args = args, decision = decision.value, tier = tier.value)

    if decision == Decision.DENY:
        return ToolResult(ok = False, content = f"Denied by policy {tool.name} is not permitted",)
    if decision == Decision.NEEDS_APPROVAL and not approved and not tool.upgrade_stub:
        return ToolResult(ok = False, content = f"{tool.name} requires human approval and was not executed",)
    result = await dispatch(tool, args)
    if result.ok and not tool.upgrade_stub and not result.content.lstrip().lower().startswith(_FAILED):
        await _keep(tool.name, args)
    return result


async def _keep(name: str, args: dict) -> None:
    """Log an outward action for the Kept tab, when a run is the cause
    (harness/provenance.py). Bookkeeping: it never fails the call."""
    from harness import provenance
    src = provenance.current()
    if src is None or provenance.app_for(name) is None:
        return
    try:
        from harness.db.kept import record_action
        await asyncio.to_thread(record_action, src, name, args)
    except Exception as e:  # noqa: BLE001
        log.warning("kept action not recorded", tool=name, error=str(e))
