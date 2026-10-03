"""The billing plans: which model tiers, efforts and modes each one unlocks,
and how many dollars of model cost it includes per period.

Prices shown here are for display only -- what the buyer is charged is set on
the Dodo Payments product. Allowances come from settings so they can be tuned
without a deploy of this table.
"""

from dataclasses import dataclass

from harness.config import get_settings
from harness.providers.registry import Effort, ModelSpec, Tier, list_models

EFFORT_ORDER: tuple[Effort, ...] = ("minimal", "low", "medium", "high", "xhigh")
WEEK_MINUTES = 7 * 24 * 60


@dataclass(frozen=True)
class Plan:
    id: str
    label: str
    price_usd_month: float
    model_tiers: tuple[Tier, ...]
    max_effort: Effort
    research_allowed: bool
    # scheduled tasks may run at most this often (Free: weekly; the daily brief is Plus)
    task_min_minutes: int = 15

    @property
    def monthly_allowance_usd(self) -> float:
        return float(getattr(get_settings(), f"billing_allowance_{self.id}"))

    def allows_model(self, spec: ModelSpec) -> bool:
        return spec.tier in self.model_tiers

    def allows_effort(self, effort: Effort | None) -> bool:
        return effort is None or EFFORT_ORDER.index(effort) <= EFFORT_ORDER.index(self.max_effort)

    def default_model(self) -> ModelSpec:
        """First allowed model in registry (UI) order."""
        return next(s for s in list_models() if self.allows_model(s))

    def to_dict(self) -> dict:
        return {"id": self.id, "label": self.label, "price_usd_month": self.price_usd_month,
                "model_tiers": list(self.model_tiers), "max_effort": self.max_effort,
                "research_allowed": self.research_allowed, "task_min_minutes": self.task_min_minutes,
                "monthly_allowance_usd": self.monthly_allowance_usd}


PLANS: dict[str, Plan] = {p.id: p for p in (
    Plan("free", "Free", 0, ("basic",), "medium", research_allowed=False, task_min_minutes=WEEK_MINUTES),
    Plan("plus", "Plus", 20, ("basic", "advanced"), "xhigh", research_allowed=True),
    Plan("pro", "Pro", 100, ("basic", "advanced", "frontier"), "xhigh", research_allowed=True),
)}

FREE = PLANS["free"]

# Tools that need a paid plan: name or fnmatch pattern -> (cheapest plan,
# what the user sees). Everything else is available on every plan.
GATED_TOOLS: dict[str, tuple[str, str]] = {
    "create_file": ("plus", "Creating files (PDF, Word, Excel, slides)"),
    "analyze_data": ("plus", "Spreadsheet analysis and charts"),
    "maps_search": ("plus", "Maps and places"),
    "travel_time": ("plus", "Travel times and directions"),
    # Google: Free reads and summarises; acting on the user's behalf is Plus
    "gmail__send_*": ("plus", "Sending email"),
    "gmail__create_draft": ("plus", "Drafting email replies"),
    "calendar__create_event": ("plus", "Adding calendar events"),
    "calendar__update_event": ("plus", "Changing calendar events"),
    "calendar__delete_event": ("plus", "Deleting calendar events"),
    "sheets__append_rows": ("plus", "Writing to Google Sheets"),
    "sheets__create_spreadsheet": ("plus", "Creating Google Sheets"),
    "docs__append_text": ("plus", "Writing to Google Docs"),
    "generate_image": ("pro", "Image generation"),
    "github__*": ("pro", "The GitHub connector"),
    "notion__*": ("pro", "The Notion connector"),
    "slack__*": ("pro", "The Slack connector"),
}

_RANK = {p: i for i, p in enumerate(PLANS)}


def gate_for(tool_name: str) -> tuple[str, str] | None:
    import fnmatch
    return GATED_TOOLS.get(tool_name) or next(
        (v for k, v in GATED_TOOLS.items() if "*" in k and fnmatch.fnmatch(tool_name, k)), None)


def plan_allows_tool(plan: Plan, tool_name: str) -> bool:
    need = gate_for(tool_name)
    return need is None or _RANK[plan.id] >= _RANK[need[0]]


def get_plan(plan_id: str | None) -> Plan:
    return PLANS.get(plan_id or "free", FREE)


def cheapest_plan_for(spec: ModelSpec) -> Plan:
    """The plan a locked model needs -- what the upgrade prompt names."""
    return next(p for p in PLANS.values() if p.allows_model(spec))
