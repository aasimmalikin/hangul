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


@dataclass(frozen=True)
class Plan:
    id: str
    label: str
    price_usd_month: float
    model_tiers: tuple[Tier, ...]
    max_effort: Effort
    research_allowed: bool

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
                "research_allowed": self.research_allowed,
                "monthly_allowance_usd": self.monthly_allowance_usd}


PLANS: dict[str, Plan] = {p.id: p for p in (
    Plan("free", "Free", 0, ("basic",), "medium", research_allowed=False),
    Plan("plus", "Plus", 20, ("basic", "advanced"), "xhigh", research_allowed=True),
    Plan("pro", "Pro", 100, ("basic", "advanced", "frontier"), "xhigh", research_allowed=True),
)}

FREE = PLANS["free"]


def get_plan(plan_id: str | None) -> Plan:
    return PLANS.get(plan_id or "free", FREE)


def cheapest_plan_for(spec: ModelSpec) -> Plan:
    """The plan a locked model needs -- what the upgrade prompt names."""
    return next(p for p in PLANS.values() if p.allows_model(spec))
