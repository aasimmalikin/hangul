from harness.policy.audit import AuditLog
from harness.policy.policy import ToolPolicy
from harness.policy.tiers import Decision
from harness.tools.base import Tool, ToolResult
from harness.tools.dispatch import dispatch

async def guarded_dispatch(tool: Tool, args: dict, policy: ToolPolicy, audit: AuditLog, approved: bool = False)->ToolResult:
    decision = policy.decide(tool.name)
    tier = policy.tier_of(tool.name)
    audit.record(tool = tool.name, args = args, decision = decision.value, tier = tier.value)

    if decision == Decision.DENY:
        return ToolResult(ok = False, content = f"Denied by policy {tool.name} is not permitted",)
    if decision == Decision.NEEDS_APPROVAL and not approved and not tool.upgrade_stub:
        return ToolResult(ok = False, content = f"{tool.name} requires human approval and was not executed",)
    return await dispatch(tool, args)

