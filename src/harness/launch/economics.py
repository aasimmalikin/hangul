"""Unit economics for a launch plan: plain arithmetic, never the model.

The model (and sourcing) only supply inputs -- prices, quantities and the
assumptions the user can edit; every number on the dashboard comes from
``compute``, so it is the same every time and changes the instant the user
moves a slider, with no model call.

Definitions (per month unless said otherwise):
  revenue          price x units per day x days open
  contribution     what a sale leaves after its variable costs: price x (1 - variable share)
  fixed            the monthly items that are switched on (rent, salaries, utilities…)
  profit           contribution x units - fixed
  break-even       fixed / contribution per sale, in sales per day
  start-up cost    one-off items + working capital (fixed costs for N months, to survive the slow start)
  payback          start-up cost / profit, in months (None when the business loses money)
"""

import math

SCENARIOS = {
    # how far the worst and best cases move from the user's own numbers
    "worst": {"units": 0.7, "price": 0.95, "variable": 0.05},
    "likely": {"units": 1.0, "price": 1.0, "variable": 0.0},
    "best": {"units": 1.3, "price": 1.0, "variable": -0.02},
}
MAX_VARIABLE = 0.99


def _num(v, default: float = 0.0) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    return f if math.isfinite(f) else default


def item_total(item: dict) -> float:
    """What an item costs in the plan: its amount x quantity, or 0 when switched off."""
    if not item.get("include", True):
        return 0.0
    return max(0.0, _num(item.get("amount"))) * max(0, int(_num(item.get("qty"), 1)))


def totals(items: list[dict]) -> tuple[float, float, dict[str, float]]:
    """(one-off total, monthly total, one-off + monthly by category)."""
    one_off = monthly = 0.0
    by_cat: dict[str, float] = {}
    for it in items:
        t = item_total(it)
        if it.get("monthly"):
            monthly += t
        else:
            one_off += t
        by_cat[it.get("category", "other")] = by_cat.get(it.get("category", "other"), 0.0) + t
    return one_off, monthly, by_cat


def variable_share(assumptions: dict) -> float:
    pct = sum(max(0.0, _num(v.get("pct"))) for v in assumptions.get("variable") or [])
    return min(pct, MAX_VARIABLE)


def _month(price: float, units_day: float, days: float, var: float, fixed: float) -> dict:
    revenue = price * units_day * days
    per_sale = price * (1 - var)
    contribution = per_sale * units_day * days
    profit = contribution - fixed
    breakeven_day = math.ceil(fixed / per_sale / days) if per_sale > 0 and days > 0 else None
    return {"revenue": round(revenue), "variable_costs": round(revenue - contribution),
            "contribution_per_sale": round(per_sale, 2), "fixed": round(fixed), "profit": round(profit),
            "margin": round(profit / revenue, 4) if revenue > 0 else None, "breakeven_per_day": breakeven_day}


def compute(items: list[dict], assumptions: dict, budget: float | None = None) -> dict:
    """Every number the dashboard shows."""
    price = max(0.0, _num(assumptions.get("price")))
    units = max(0.0, _num(assumptions.get("units_per_day")))
    days = min(31.0, max(1.0, _num(assumptions.get("days_per_month"), 26)))
    wc_months = min(12.0, max(0.0, _num(assumptions.get("working_capital_months"), 3)))
    var = variable_share(assumptions)
    one_off, fixed, by_cat = totals(items)

    likely = _month(price, units, days, var, fixed)
    working_capital = fixed * wc_months
    startup = one_off + working_capital
    profit = likely["profit"]
    payback = round(startup / profit, 1) if profit > 0 else None

    scenarios = {}
    for name, s in SCENARIOS.items():
        m = _month(price * s["price"], units * s["units"], days, min(MAX_VARIABLE, max(0.0, var + s["variable"])), fixed)
        m["units_per_day"] = round(units * s["units"], 1)
        m["payback_months"] = round(startup / m["profit"], 1) if m["profit"] > 0 else None
        scenarios[name] = m

    # the break-even chart: revenue vs total cost from 0 to twice break-even (or twice the plan)
    top = max(units * 1.5, (likely["breakeven_per_day"] or 0) * 2, 10)
    chart = []
    for i in range(13):
        u = top * i / 12
        rev = price * u * days
        chart.append({"units_per_day": round(u, 1), "revenue": round(rev), "costs": round(fixed + rev * var)})

    return {
        **likely,
        "units_per_day": units,
        "price": price,
        "days_per_month": days,
        "variable_share": round(var, 4),
        "one_off": round(one_off),
        "working_capital": round(working_capital),
        "working_capital_months": wc_months,
        "startup_total": round(startup),
        "payback_months": payback,
        "budget": round(budget) if budget else None,
        "budget_gap": round(budget - startup) if budget else None,
        "by_category": {k: round(v) for k, v in by_cat.items()},
        "scenarios": scenarios,
        "chart": chart,
    }
