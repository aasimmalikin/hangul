"""Turning the user's answers into a plan, and applying their edits.

Pure functions over plain dicts (what the ``launch_plans`` row stores), so
they are tested without a database.

An item in a plan::

    {key, name, category, monthly, qty, low, high, typical, amount, include,
     status: "estimate" | "sourced" | "user", sellers: [{seller, price, url, quote}],
     checked_at, why, search, local}

``amount`` is what the plan uses per unit; it starts at ``typical`` and a
number the user types makes the item ``user`` (sourcing never overwrites it).
"""

import math

from harness.launch import kinds

QUESTIONS = ("kind", "city", "size")          # the plan can't be made without these
MAX_BUDGET = 10_000_000_000
MAX_AMOUNT = 1_000_000_000


class BadAnswer(ValueError):
    pass


def title_for(kind: kinds.Kind, city: str, area: str = "") -> str:
    where = ", ".join(x for x in (area.strip(), city.strip()) if x)
    return f"{kind.label} in {where}"[:120] if where else kind.label


def new_plan(*, kind: str, city: str, size: str, area: str = "", renting: str = "yes", budget: float | None = None,
             start: str = "", note: str = "") -> dict:
    """The fields of a new plan, all estimates, ready to save."""
    k = kinds.get(kind)
    if k is None:
        raise BadAnswer(f"kind must be one of {', '.join(kinds.KINDS)}")
    if size not in kinds.SIZES:
        raise BadAnswer(f"size must be one of {', '.join(kinds.SIZES)}")
    if renting not in kinds.RENTING:
        raise BadAnswer(f"renting must be one of {', '.join(kinds.RENTING)}")
    city, area = " ".join((city or "").split())[:80], " ".join((area or "").split())[:120]
    if not city:
        raise BadAnswer("city is required")
    if budget is not None and not (0 <= budget <= MAX_BUDGET):
        raise BadAnswer("budget is out of range")

    items = []
    for it in k.items:
        qty = it.qty_for(size)
        if qty <= 0:
            continue
        low, high = it.range_for(size)
        typical = round((low + high) / 2)
        items.append({
            "key": it.key, "name": it.name, "category": it.category, "monthly": it.monthly, "qty": qty,
            "low": low, "high": high, "typical": typical, "amount": typical,
            "include": not it.needs_rent or renting == "yes",
            "status": "estimate", "sellers": [], "checked_at": None, "why": it.why,
            "search": it.search, "local": it.local,
        })
    assumptions = {
        "price": k.price,
        "units_per_day": k.units_per_day[kinds.SIZES.index(size)],
        "days_per_month": k.days_per_month,
        "working_capital_months": 3,
        "variable": [{"key": v.key, "label": v.label, "pct": v.pct} for v in k.variable],
    }
    benchmarks = [{"key": b.key, "label": b.label, "query": b.query, "typical": b.typical, "value": b.typical,
                   "source": None, "quote": "", "status": "estimate", "checked_at": None} for b in k.benchmarks]
    return {
        "title": title_for(k, city, area), "kind": k.key, "city": city, "area": area,
        "answers": {"size": size, "renting": renting, "budget": budget, "start": (start or "")[:60],
                    "note": (note or "")[:500]},
        "items": items, "assumptions": assumptions, "benchmarks": benchmarks, "suppliers": [],
    }


def _clip(v, lo: float, hi: float) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError) as e:
        raise BadAnswer("not a number") from e
    if math.isnan(f) or not (lo <= f <= hi):
        raise BadAnswer(f"must be between {lo:g} and {hi:g}")
    return f


def apply_edits(items: list[dict], assumptions: dict, patch: dict) -> tuple[list[dict], dict]:
    """The user's changes from the dashboard. ``patch`` keys: price, units_per_day,
    days_per_month, working_capital_months, variable {key: pct}, items {key: {amount?, qty?, include?}}."""
    a = dict(assumptions)
    for key, lo, hi in (("price", 0, 10_000_000), ("units_per_day", 0, 100_000), ("days_per_month", 1, 31),
                        ("working_capital_months", 0, 12)):
        if patch.get(key) is not None:
            a[key] = _clip(patch[key], lo, hi)
    if patch.get("variable"):
        changes = patch["variable"]
        a["variable"] = [{**v, "pct": _clip(changes[v["key"]], 0, 0.99)} if v["key"] in changes else v
                         for v in a.get("variable") or []]
    out = []
    edits = patch.get("items") or {}
    for it in items:
        e = edits.get(it["key"])
        if not e:
            out.append(it)
            continue
        it = dict(it)
        if e.get("amount") is not None:
            it["amount"] = round(_clip(e["amount"], 0, MAX_AMOUNT))
            it["status"] = "user"
        if e.get("qty") is not None:
            it["qty"] = int(_clip(e["qty"], 0, 1000))
        if e.get("include") is not None:
            it["include"] = bool(e["include"])
        out.append(it)
    unknown = set(edits) - {it["key"] for it in items}
    if unknown:
        raise BadAnswer(f"no such item: {min(unknown)}")
    return out, a


def to_source(items: list[dict], limit: int) -> list[dict]:
    """The items worth a search, most expensive first, at most ``limit``."""
    cands = [it for it in items if it.get("search") and it.get("include", True)]
    cands.sort(key=lambda it: it.get("high", 0) * it.get("qty", 1) * (12 if it.get("monthly") else 1), reverse=True)
    return cands[:max(0, limit)]


def local_queries(items: list[dict]) -> list[str]:
    return list(dict.fromkeys(it["local"] for it in items if it.get("local") and it.get("include", True)))
