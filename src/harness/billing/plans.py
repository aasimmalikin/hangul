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
    # brands (harness.brands) included; more are bought as one-time slots
    brands_included: int = 0
    # launch plans (harness.launch) with live prices per month; every plan gets estimate-only ones
    launch_sourced_month: int = 0
    # businesses tracked in How's business (harness.sales)
    businesses_included: int = 1

    @property
    def monthly_allowance_usd(self) -> float:
        return float(getattr(get_settings(), f"billing_allowance_{self.id}"))

    def allowance_usd(self, region: str = "intl") -> float:
        """Monthly allowance at this region's prices: Indian plans cost less, so
        they include less model usage (billing_allowance_<plan>_in)."""
        if region == "in" and self.id != "free":
            return float(getattr(get_settings(), f"billing_allowance_{self.id}_in"))
        return self.monthly_allowance_usd

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
                "brands_included": self.brands_included,
                "launch_sourced_month": self.launch_sourced_month,
                "businesses_included": self.businesses_included,
                "best_for": BEST_FOR.get(self.id, ""),
                "monthly_allowance_usd": self.monthly_allowance_usd}


PLANS: dict[str, Plan] = {p.id: p for p in (
    Plan("free", "Free", 0, ("basic",), "medium", research_allowed=False, task_min_minutes=WEEK_MINUTES),
    Plan("plus", "Plus", 20, ("basic", "advanced"), "xhigh", research_allowed=True, brands_included=1,
         launch_sourced_month=1),
    Plan("pro", "Pro", 100, ("basic", "advanced", "frontier"), "xhigh", research_allowed=True, brands_included=3,
         launch_sourced_month=20, businesses_included=5),
)}

FREE = PLANS["free"]

# Who each plan is for (the pricing page's "Best for"), and the plan suggested
# for each persona (db/settings.PERSONAS; only "founder", the business owner, is still
# offered): Plus is the plan for a shop, Pro for owners with several outlets.
BEST_FOR: dict[str, str] = {
    "free": "Logging sales, reminders and your customer list, on WhatsApp too",
    "plus": "A shop or small business: tomorrow's forecast, a slow day handled each week and posts in your brand",
    "pro": "Busy owners and several outlets: every slow day handled, up to 5 businesses and 3 brands",
}
RECOMMENDED: dict[str, str] = {
    "founder": "plus", "developer": "pro", "student": "plus", "professional": "plus", "personal": "plus",
}

# ------------------------------------------------------------------ regional prices
# Display only: what the buyer pays is the Dodo product's price. "in" products
# are priced in rupees (UPI AutoPay works with them); yearly = 2 months free.
REGIONS = ("intl", "in")
INTERVALS = ("month", "year")


@dataclass(frozen=True)
class Price:
    amount: float
    currency: str            # "USD" | "INR"
    label: str               # "$20", "₹499"

    def to_dict(self) -> dict:
        return {"amount": self.amount, "currency": self.currency, "label": self.label}


PRICES: dict[tuple[str, str, str], Price] = {
    ("plus", "intl", "month"): Price(20, "USD", "$20"),
    ("plus", "intl", "year"): Price(200, "USD", "$200"),
    ("pro", "intl", "month"): Price(100, "USD", "$100"),
    ("pro", "intl", "year"): Price(1000, "USD", "$1,000"),
    ("plus", "in", "month"): Price(499, "INR", "₹499"),
    ("plus", "in", "year"): Price(4999, "INR", "₹4,999"),
    ("pro", "in", "month"): Price(1499, "INR", "₹1,499"),
    ("pro", "in", "year"): Price(14999, "INR", "₹14,999"),
    # one more brand, paid once (harness.brands)
    ("brand_slot", "intl", "once"): Price(5, "USD", "$5"),
    ("brand_slot", "in", "once"): Price(399, "INR", "₹399"),
}

# Timezones that get Indian prices. The device timezone (user_settings, which
# follows the browser) decides what is offered; what was bought is stored as
# users.plan_region from the product the webhook reports.
INDIA_TIMEZONES = {"Asia/Kolkata", "Asia/Calcutta"}


def region_for_timezone(tz: str | None) -> str:
    return "in" if tz in INDIA_TIMEZONES else "intl"


def product_key(plan: str, region: str = "intl", interval: str = "month") -> str:
    """The Dodo product setting for a plan: plus, plus_annual, plus_in, plus_in_annual…"""
    return plan + ("_in" if region == "in" else "") + ("_annual" if interval == "year" else "")


def parse_product_key(key: str) -> tuple[str, str, str]:
    """product_key's inverse: "pro_in_annual" -> ("pro", "in", "year")."""
    parts = key.split("_")
    return parts[0], "in" if "in" in parts[1:] else "intl", "year" if "annual" in parts[1:] else "month"


def prices_for(plan: str, region: str) -> dict:
    return {i: PRICES[(plan, region, i)].to_dict() for i in INTERVALS if (plan, region, i) in PRICES}

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
    # Google Meet is Plus and up: instant links, past calls and transcripts (a Meet link on a new
    # event comes with calendar__create_event, already Plus)
    "meet__*": ("plus", "Google Meet"),
    "generate_image": ("pro", "Image generation"),
    "edit_image": ("pro", "Editing your photos"),
    "finish_image": ("plus", "Brand posts (your text, logo and sizes)"),
    "brands": ("plus", "Brands"),
    "write_caption": ("plus", "Captions for your posts"),
    # Brand Studio features that aren't tools (checked by routes/brands.py)
    "brand_studio": ("plus", "The Brand Studio"),
    "brand_carousel": ("pro", "Carousel posts"),
    "brand_review": ("pro", "Client review links"),
    # launch plans: the checklist and calculator are free; live prices and sellers are Plus
    "launch_sourcing": ("plus", "Live prices and sellers for your launch plan"),
    # How's business: logging and the weekly summary are free; tomorrow's forecast is Plus;
    # why, and an idea for every slow day, are Pro (Plus gets one idea a week)
    "sales_forecast": ("plus", "Tomorrow's sales forecast"),
    "sales_reasons": ("pro", "Why tomorrow looks the way it does"),
    "sales_ideas": ("pro", "An idea for every slow day"),
    "sales_whatsapp": ("pro", "Slow-day alerts on WhatsApp"),
    # missions (harness.missions): Hangul carries a slow day through on its own
    "missions": ("plus", "Hangul handles your slow days for you"),
    # Kept your word (harness.promises): promises told in chat and their due-day nudges are free;
    # finding them in email, asking after meetings and chasing are Plus (not tools: service.access)
    "promises_email": ("plus", "Finding promises in your email"),
    "promises_meetings": ("plus", "Asking what was promised after your meetings"),
    "promises_chase": ("plus", "Chasing promises owed to you"),
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
