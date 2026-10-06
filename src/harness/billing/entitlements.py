"""May this user run this model, at this effort, in this mode, right now?

Called wherever a run picks its model -- ``/ask``, ``/ask/stream``,
``/approve`` and the scheduler -- before any token is spent. Refusals are
``402`` with an ``X-Reason`` the UI turns into an upgrade or buy-credits card:

  plan_required          the model's tier is not in the plan
  effort_not_allowed     the effort is above the plan's ceiling
  research_requires_plan deep-research mode on the free plan
  insufficient_balance   allowance used up and no credits left
  free_pool_exhausted    free users together hit this month's free budget
                         (``billing_free_pool_usd``) and this one has no credits

Billing is off (every check passes) until ``dodo_api_key`` is set, so
dev machines and the test suite behave exactly as before.
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException

from harness.billing.plans import EFFORT_ORDER, Plan, cheapest_plan_for, get_plan
from harness.config import get_settings
from harness.db import billing as billing_db
from harness.db import ledger
from harness.providers.registry import Effort, ModelSpec, default_model_id, get_model, resolve


@dataclass
class Standing:
    """A user's plan and what is left of it this period."""
    plan: Plan
    account: billing_db.Account
    period_start: datetime
    allowance_left: Decimal
    credits: Decimal
    # free plan only: the shared monthly budget is used up, so the allowance
    # cannot be drawn on -- bought credits still can
    pool_exhausted: bool = False
    allowance: Decimal = Decimal("0")       # this period's full allowance (the trial's while trialling)

    @property
    def usable_allowance(self) -> Decimal:
        return Decimal("0") if self.pool_exhausted else max(self.allowance_left, Decimal("0"))

    @property
    def can_spend(self) -> bool:
        return self.usable_allowance + self.credits > 0


# plan_status while a Plus trial runs (before the first real charge); the
# allowance is billing_allowance_trial instead of the plan's
TRIAL_STATUSES = ("trialing", "trial_cancelling")


def allowance_for(account: billing_db.Account, plan: Plan) -> Decimal:
    if plan.id != "free" and account.plan_status in TRIAL_STATUSES:
        return Decimal(str(get_settings().billing_allowance_trial))
    return Decimal(str(plan.allowance_usd(getattr(account, "plan_region", "intl") or "intl")))


_per_message: tuple[float, Decimal] | None = None     # (fetched at, $) -- cached for 10 minutes


def usd_per_message() -> Decimal:
    """What one message costs on average: the last 14 days' runs, else the setting."""
    import time
    global _per_message
    if _per_message is not None and time.monotonic() - _per_message[0] < 600:
        return _per_message[1]
    from datetime import timedelta
    try:
        avg = ledger.average_run_cost(datetime.now(timezone.utc) - timedelta(days=14))
    except Exception:  # noqa: BLE001 - an estimate must never fail a page
        avg = None
    value = avg if avg and avg > 0 else Decimal(str(get_settings().billing_usd_per_message))
    _per_message = (time.monotonic(), value)
    return value


def messages_for(usd: Decimal | float) -> int:
    """About how many messages ``usd`` of allowance buys."""
    per = usd_per_message()
    return max(int(Decimal(str(usd)) / per), 0) if per > 0 else 0


def billing_enabled() -> bool:
    return bool(get_settings().dodo_api_key)


def month_start(now: datetime | None = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def free_pool_exhausted() -> bool:
    """True once free users together have spent ``billing_free_pool_usd`` this UTC month."""
    pool = get_settings().billing_free_pool_usd
    if pool is None:
        return False
    return ledger.free_pool_spent(month_start()) >= Decimal(str(pool))


def _add_months(dt: datetime, months: int) -> datetime:
    """Same day-of-month ``months`` later, clamped to the month's last day (31 Jan + 1 = 28/29 Feb)."""
    import calendar
    y, m = divmod(dt.month - 1 + months, 12)
    year, month = dt.year + y, m + 1
    return dt.replace(year=year, month=month, day=min(dt.day, calendar.monthrange(year, month)[1]))


def period_start(account: billing_db.Account, now: datetime | None = None) -> datetime:
    """Paid plans count from the last renewal; free counts per UTC calendar month.
    A yearly plan's allowance is still monthly: it counts from the latest
    monthly anniversary of the paid period's start."""
    now = now or datetime.now(timezone.utc)
    if account.plan != "free" and account.plan_period_start is not None:
        start = account.plan_period_start
        if getattr(account, "plan_interval", "month") == "year":
            months = (now.year - start.year) * 12 + now.month - start.month
            anniversary = _add_months(start, months)
            if anniversary > now:
                anniversary = _add_months(start, months - 1)
            return max(anniversary, start)
        return start
    return month_start(now)


def standing(user_id: str) -> Standing:
    account = billing_db.get_account(user_id)
    plan = get_plan(account.plan)
    since = period_start(account)
    try:
        used = ledger.period_usage(user_id, since)
        credits = ledger.credit_balance(user_id)
    except ValueError:              # non-numeric subject: no ledger rows
        used, credits = Decimal("0"), Decimal("0")
    allowance = allowance_for(account, plan)
    pool_out = plan.id == "free" and free_pool_exhausted()
    return Standing(plan, account, since, allowance - used, credits, pool_exhausted=pool_out, allowance=allowance)


def _deny(reason: str, detail: str, **extra) -> HTTPException:
    return HTTPException(status_code=402, detail={"detail": detail, "code": reason, **extra},
                         headers={"X-Reason": reason})


def _clamp_effort(spec: ModelSpec, plan: Plan) -> Effort | None:
    """The effort ``resolve()`` would pick, lowered to the plan's ceiling."""
    allowed = [e for e in spec.efforts if plan.allows_effort(e)]
    for preferred in (get_settings().default_effort, spec.default_effort):
        if preferred in allowed:
            return preferred  # type: ignore[return-value]
    return max(allowed, key=EFFORT_ORDER.index) if allowed else None


def _resolve_or_422(model: str | None, effort: str | None) -> tuple[ModelSpec, Effort | None]:
    try:
        return resolve(model, effort)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


def resolve_for_user(user_id: str, model: str | None, effort: str | None, *,
                     mode: str = "default",
                     fallback_model: str | None = None, fallback_effort: str | None = None,
                     check_balance: bool = True,
                     plan_standing: Standing | None = None,
                     question: str = "") -> tuple[ModelSpec, Effort | None]:
    """``resolve()`` plus the plan.

    ``model``/``effort`` are what the caller asked for: refused with 402 if
    the plan does not cover them. ``fallback_*`` are inherited (a
    conversation's stored settings): a downgraded user is quietly moved to a
    model their plan covers instead of being locked out of their own chat.
    """
    from harness.providers import router
    auto = model == router.AUTO or (model is None and fallback_model == router.AUTO)

    if not billing_enabled():
        if auto:
            c = router.choose(question, mode)
            return _resolve_or_422(c.model, c.effort)
        return _resolve_or_422(model or fallback_model, effort or fallback_effort)

    st = plan_standing or standing(user_id)
    plan = st.plan

    if auto:
        # picks only what the plan includes, at a depth it allows -- never a 402 for the model
        if mode == "research" and not plan.research_allowed:
            raise _deny("research_requires_plan", "Deep research needs the Plus plan.", plan_needed="plus")
        c = router.choose(question, mode, allowed=plan.allows_model, max_effort=plan.max_effort)
        resolved = _resolve_or_422(c.model, c.effort)
        if check_balance and not st.can_spend:
            if st.pool_exhausted and st.allowance_left > 0:
                raise _deny("free_pool_exhausted", "Free capacity is full for this month. Upgrade or buy credits to keep going.",
                            plan_needed="plus")
            raise _deny("insufficient_balance", "You've used this period's allowance. Upgrade or buy credits to continue.",
                        plan_needed="plus" if plan.id == "free" else None)
        return resolved

    if mode == "research" and not plan.research_allowed:
        raise _deny("research_requires_plan", "Deep research needs the Plus plan.",
                    plan_needed="plus")

    chosen = model
    if chosen is None:
        inherited = get_model(fallback_model) if fallback_model else None
        if inherited is not None and plan.allows_model(inherited):
            chosen = inherited.id
        else:
            default = get_model(default_model_id())
            chosen = default.id if default and plan.allows_model(default) else plan.default_model().id

    spec = get_model(chosen)
    if spec is None:
        _resolve_or_422(chosen, effort)                 # raises the 422
    if not plan.allows_model(spec):
        needed = cheapest_plan_for(spec)
        raise _deny("plan_required", f"{spec.label} needs the {needed.label} plan.",
                    plan_needed=needed.id, model=spec.id)

    if effort is not None and not plan.allows_effort(effort):
        raise _deny("effort_not_allowed",
                    f"Effort '{effort}' needs a paid plan (yours allows up to '{plan.max_effort}').",
                    plan_needed="plus")
    chosen_effort = effort
    if (chosen_effort is None and fallback_effort in spec.efforts
            and plan.allows_effort(fallback_effort)):
        chosen_effort = fallback_effort                 # inherited, and still allowed
    if chosen_effort is None and spec.supports_reasoning:
        chosen_effort = _clamp_effort(spec, plan)

    resolved = _resolve_or_422(spec.id, chosen_effort)

    if check_balance and not st.can_spend and st.pool_exhausted and st.allowance_left > 0:
        raise _deny("free_pool_exhausted",
                    "Free capacity is full for this month. Upgrade or buy credits to keep going.",
                    plan_needed="plus")
    if check_balance and not st.can_spend:
        raise _deny("insufficient_balance",
                    "You've used this period's allowance. Upgrade or buy credits to continue.",
                    plan_needed="plus" if plan.id == "free" else None)
    return resolved


async def aresolve_for_user(user_id: str, model: str | None, effort: str | None, **kw):
    """``resolve_for_user`` off the event loop (it reads the DB)."""
    if not billing_enabled():
        return resolve_for_user(user_id, model, effort, **kw)
    return await asyncio.to_thread(resolve_for_user, user_id, model, effort, **kw)


def _upgrade_stub(tool, plan_needed: str, feature: str):
    """Same name and schema, so the model still knows the capability exists and
    can offer it; calling it explains the plan and puts an upgrade card in the
    chat instead of doing the work."""
    from harness.tools.base import Tool, ToolOutput

    async def needs_plan(**_kw):
        label = get_plan(plan_needed).label
        return ToolOutput(
            f"{feature} is part of the {label} plan, and this user is on Free. Tell them briefly and offer the "
            f"upgrade (the card below has the button); do not try to work around it.",
            {"kind": "upgrade", "feature": feature, "plan": plan_needed, "plan_label": label})

    return Tool(name=tool.name, description=tool.description, parameter=tool.parameter, handler=needs_plan,
                upgrade_stub=True)


def gate_tools(user_id: str, tools: list) -> list:
    """Swap the tools this user's plan does not include for upgrade stubs.
    Billing off = everything is included."""
    from harness.billing.plans import gate_for, plan_allows_tool
    if not billing_enabled():
        return tools
    plan = get_plan(billing_db.get_account(user_id).plan)
    return [t if plan_allows_tool(plan, t.name) else _upgrade_stub(t, *gate_for(t.name)) for t in tools]


async def gate_registry(user_id: str, registry) -> None:
    """Apply the plan to a whole run's tool registry (built-ins and connectors
    alike): re-registering under the same name replaces the tool."""
    if not billing_enabled():
        return
    for t in await asyncio.to_thread(gate_tools, user_id, registry.list()):
        registry.registry(t)


def allows_research(user_id: str) -> bool:
    if not billing_enabled():
        return True
    return get_plan(billing_db.get_account(user_id).plan).research_allowed


def settle(user_id: str, cost: Decimal, thread_id: str | None) -> None:
    """Charge a finished run (allowance first, then credits). With billing off
    the cost is still recorded, as before, so spend stays visible."""
    if not billing_enabled():
        ledger.record_transaction(user_id=user_id, amount=-cost, kind="run_cost", thread_id=thread_id)
        return
    account = billing_db.get_account(user_id)
    plan = get_plan(account.plan)
    free = plan.id == "free"
    # once the free pool is spent, a free user's run is paid from credits only
    allowance = Decimal("0") if free and free_pool_exhausted() else allowance_for(account, plan)
    ledger.settle_run(user_id, cost, allowance=allowance, since=period_start(account),
                      thread_id=thread_id, allowance_kind="free_cost" if free else "run_cost")
