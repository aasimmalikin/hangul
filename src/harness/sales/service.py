"""How's business: everything the page, the chat tool and the evening alert
need for one business, with the plan split applied in one place.

  Free   log days (chat, WhatsApp, page, spreadsheet), the week so far, history
  Plus   + tomorrow's forecast with its range and accuracy, the slow-day flag,
           and one idea a week (``sales_plus_ideas_week``), margin-checked
  Pro    + why (the forecast's reasons), an idea for every slow day,
           alerts on WhatsApp as well as push, and up to 5 businesses

Nothing here calls a language model.
"""

import asyncio
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from harness.config import get_settings
from harness.db import sales as db
from harness.launch import kinds as launch_kinds
from harness.logging import log
from harness.sales import festivals, playbook, weather
from harness.sales import forecast as fc

HISTORY_DAYS = 400
CHART_DAYS = 42


# ------------------------------------------------------------ who may see what

def access(user_id: str) -> dict:
    from harness.billing import entitlements
    from harness.billing.plans import get_plan, plan_allows_tool
    if not entitlements.billing_enabled():
        return {"plan": None, "forecast": True, "reasons": True, "ideas": "all", "whatsapp": True}
    from harness.db import billing as billing_db
    plan = get_plan(billing_db.get_account(user_id).plan)
    ok = lambda f: plan_allows_tool(plan, f)
    return {"plan": plan.id, "forecast": ok("sales_forecast"), "reasons": ok("sales_reasons"),
            "ideas": "all" if ok("sales_ideas") else "weekly" if ok("sales_forecast") else "none",
            "whatsapp": ok("sales_whatsapp")}


def local_today(user_id: str) -> date:
    from harness.db.settings import get_settings as user_settings
    try:
        tz = ZoneInfo(user_settings(user_id).timezone or "UTC")
    except Exception:  # noqa: BLE001 - a bad stored zone falls back to UTC
        tz = ZoneInfo("UTC")
    return datetime.now(tz).date()


def week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def ideas_left(business_id: int, today: date) -> int:
    used = [e for e in db.events(business_id, "idea_used", week_start(today))
            if date.fromisoformat(e["day"]) < week_start(today) + timedelta(days=7) + timedelta(days=1)]
    return max(0, get_settings().sales_plus_ideas_week - len(used))


# ------------------------------------------------------------ the plan it came from

def _plan_numbers(user_id: str, launch_plan_id: int | None) -> dict:
    """Break-even sales per day, price and assumptions from the linked launch plan."""
    if not launch_plan_id:
        return {}
    from harness.db import launch as launch_db
    p = launch_db.get(user_id, launch_plan_id)
    if p is None:
        return {}
    e = p["economics"]
    keep = 1 - e["variable_share"]
    be = e["fixed"] / keep / e["days_per_month"] if keep > 0 and e["days_per_month"] else None
    return {"breakeven": round(be) if be else None, "price": e["price"], "assumptions": p["assumptions"],
            "plan_title": p["title"], "planned_per_day": round(e["revenue"] / e["days_per_month"]) if e["days_per_month"] else None}


# ------------------------------------------------------------ weather

async def _coords(user_id: str, b: dict) -> tuple[float, float] | None:
    if b.get("lat") is not None and b.get("lon") is not None:
        return b["lat"], b["lon"]
    if not b.get("city"):
        return None
    got = await weather.geocode(b["city"])
    if got:
        await asyncio.to_thread(db.update, user_id, b["id"], lat=got[0], lon=got[1])
    return got


async def _fill_weather(user_id: str, b: dict, days: list[dict], today: date) -> dict[date, tuple]:
    """Write missing past weather onto the days; return tomorrow's (and anything fetched)."""
    xy = await _coords(user_id, b)
    if xy is None:
        return {}
    missing = [date.fromisoformat(d["day"]) for d in days if d["rain_mm"] is None and not d["closed"]]
    start = min(missing) if missing else today
    got = await weather.days(xy[0], xy[1], start, today + timedelta(days=1), today)
    past = {d: v for d, v in got.items() if d in set(missing)}
    if past:
        await asyncio.to_thread(db.set_weather, b["id"], past)
        for d in days:
            v = past.get(date.fromisoformat(d["day"]))
            if v:
                d["rain_mm"], d["tmax"] = v
    return got


# ------------------------------------------------------------ the overview

def _history(days: list[dict], promo_days: set[date]) -> list[fc.Day]:
    return [fc.Day(date.fromisoformat(d["day"]), d["sales"], d["rain_mm"], d["tmax"],
                   d["promo"] or date.fromisoformat(d["day"]) in promo_days)
            for d in days if not d["closed"] and not d["partial"]]


def _week(days: list[dict], today: date) -> dict:
    ws = week_start(today)
    this = [d for d in days if ws <= date.fromisoformat(d["day"]) <= today and not d["closed"]]
    last = [d for d in days if ws - timedelta(days=7) <= date.fromisoformat(d["day"]) <= today - timedelta(days=7) and not d["closed"]]
    tot, prev = sum(d["sales"] for d in this), sum(d["sales"] for d in last)
    return {"total": round(tot), "days": len(this), "bills": sum(d["bills"] or 0 for d in this),
            "last_week_same_days": round(prev) if last else None,
            "change": round(tot / prev - 1, 3) if last and prev > 0 else None,
            "best": max(this, key=lambda d: d["sales"])["day"] if this else None}


def _expected_series(hist: list[fc.Day], model: str | None) -> list[dict]:
    """What the chosen model would have said for each of the last weeks, one day ahead (the chart's second line)."""
    if not model or len(hist) < fc.MIN_DAYS:
        return []
    fn, min_train = fc.MODELS[model]
    out = []
    for i in range(max(min_train, len(hist) - CHART_DAYS), len(hist)):
        d = hist[i]
        out.append({"day": d.day.isoformat(), "expected": round(max(0.0, fn(hist[:i], fc.Target(d.day, d.rain, d.tmax, d.promo))))})
    return out


async def overview(user_id: str, business_id: int, *, with_weather: bool = True) -> dict | None:
    b = await asyncio.to_thread(db.get, user_id, business_id)
    if b is None:
        return None
    acc = await asyncio.to_thread(access, user_id)
    today = await asyncio.to_thread(local_today, user_id)
    tomorrow = today + timedelta(days=1)
    days = await asyncio.to_thread(db.days_for, business_id, today - timedelta(days=HISTORY_DAYS))
    got: dict = {}
    if with_weather:
        try:
            got = await _fill_weather(user_id, b, days, today)
        except Exception as e:  # noqa: BLE001 - the forecast works without weather
            log.warning("sales: weather skipped", error=str(e)[:200])
    promo_days = {date.fromisoformat(e["day"]) for e in await asyncio.to_thread(db.events, business_id, "offer", today - timedelta(days=HISTORY_DAYS))}
    hist = _history(days, promo_days)
    rain_t, tmax_t = got.get(tomorrow, (None, None))
    closed_t = any(d["day"] == tomorrow.isoformat() and d["closed"] for d in days)
    target = fc.Target(tomorrow, rain_t, tmax_t, tomorrow in promo_days, closed_t)
    f = fc.forecast(hist, target).as_dict()
    plan = await asyncio.to_thread(_plan_numbers, user_id, b.get("launch_plan_id"))
    price = plan.get("price")
    if not price:
        billed = [d for d in days[-28:] if d["bills"]]
        price = round(sum(d["sales"] for d in billed) / sum(d["bills"] for d in billed)) if billed else None

    slow, why = playbook.is_slow(f, plan.get("breakeven"))
    out = {
        "business": b, "today": today.isoformat(), "tomorrow": tomorrow.isoformat(), "access": acc,
        "week": _week(days, today), "days": days[-90:], "plan": plan, "avg_bill": price,
        "weather_tomorrow": {"rain_mm": rain_t, "tmax": tmax_t} if rain_t is not None else None,
        "festival_tomorrow": festivals.festival_on(tomorrow) or (f"Day before {festivals.eve_of(tomorrow)}" if festivals.eve_of(tomorrow) else None),
        "logged_today": any(d["day"] == today.isoformat() for d in days),
        "forecast": None, "slow": None, "ideas": [], "ideas_left": None, "locked": [],
    }
    if not acc["forecast"]:
        out["locked"].append({"feature": "Tomorrow's sales forecast", "plan": "plus"})
        out["forecast"] = {"status": f["status"], "days_logged": f["days_logged"], "days_needed": f["days_needed"]}
        return out
    out["expected"] = _expected_series(hist, f.get("model"))
    if not acc["reasons"]:
        if f.get("reasons"):
            out["locked"].append({"feature": "Why tomorrow looks this way", "plan": "pro"})
        f["reasons"] = []
    out["forecast"] = f
    out["slow"] = {"slow": slow, "why": why, "breakeven": plan.get("breakeven")} if f["status"] == "ready" else None
    if slow:
        all_ideas = playbook.suggest(b["kind"], playbook.causes(f, target), tomorrow, price=price,
                                     plan_assumptions=plan.get("assumptions"))
        if acc["ideas"] == "all":
            out["ideas"] = all_ideas
        else:
            left = await asyncio.to_thread(ideas_left, business_id, today)
            out["ideas_left"] = left
            used_tomorrow = any(e["day"] == tomorrow.isoformat() for e in await asyncio.to_thread(db.events, business_id, "idea_used", tomorrow))
            out["ideas"] = all_ideas[:1] if (left > 0 or used_tomorrow) else []
            if len(all_ideas) > len(out["ideas"]):
                out["locked"].append({"feature": "An idea for every slow day", "plan": "pro"})
    return out


async def use_idea(user_id: str, business_id: int, key: str) -> dict:
    """The owner taps "Make this post": count it (Plus has a weekly allowance),
    mark tomorrow as an offer day, and return where Brand Studio opens."""
    from urllib.parse import urlencode
    ov = await overview(user_id, business_id)          # the same forecast the page showed (weather is cached)
    if ov is None:
        raise LookupError("business")
    idea = next((i for i in ov["ideas"] if i["key"] == key), None)
    if idea is None:
        raise PermissionError("This idea isn't available on your plan this week.")
    tomorrow = date.fromisoformat(ov["tomorrow"])
    already = any(e["detail"].get("key") == key for e in await asyncio.to_thread(db.events, business_id, "idea_used", tomorrow))
    if not already:
        await asyncio.to_thread(db.add_event, business_id, tomorrow, "idea_used", {"key": key, "title": idea["title"]})
        if idea.get("discount"):
            await asyncio.to_thread(db.add_event, business_id, tomorrow, "offer", {"key": key, "discount": idea["discount"]})
    q = {"tab": "create", "layout": idea["layout"], "headline": idea["headline"], "subline": idea["subline"],
         "price": idea["price"], "cta": idea["cta"], "from": "business"}
    brand_id = ov["business"].get("brand_id")
    return {"idea": idea, "brand_id": brand_id,
            "studio_url": f"/brands/{brand_id}?{urlencode({k: v for k, v in q.items() if v})}" if brand_id else "/brands"}


# ------------------------------------------------------------ logging in a sentence (the chat tool)

def kind_label(kind: str) -> str:
    k = launch_kinds.get(kind)
    return k.label if k else "Business"


# ------------------------------------------------------------ the evening alert (scheduler)

_checked: set[tuple[int, str]] = set()      # (business, local date) already looked at today


def _due_businesses() -> list[tuple[str, int]]:
    from sqlalchemy import select

    from harness.db.models import Business
    with db.SessionLocal() as s:
        return [(str(b.user_id), b.id) for b in s.execute(
            select(Business).where(Business.active.is_(True), Business.nudges.is_(True))).scalars()]


def _local_hour(user_id: str) -> int:
    from harness.db.settings import get_settings as user_settings
    try:
        tz = ZoneInfo(user_settings(user_id).timezone or "UTC")
    except Exception:  # noqa: BLE001
        tz = ZoneInfo("UTC")
    return datetime.now(tz).hour


async def evening_alerts() -> int:
    """Once a day at ``sales_nudge_hour`` local time: if tomorrow looks slow, tell
    the owner (push; WhatsApp too on Pro), at most ``sales_nudges_week`` times a week."""
    s = get_settings()
    sent = 0
    for user_id, business_id in await asyncio.to_thread(_due_businesses):
        try:
            if await asyncio.to_thread(_local_hour, user_id) != s.sales_nudge_hour:
                continue
            today = await asyncio.to_thread(local_today, user_id)
            if (business_id, today.isoformat()) in _checked:
                continue
            _checked.add((business_id, today.isoformat()))
            b = await asyncio.to_thread(db.get, user_id, business_id)
            if b is None or b["paused"]:
                continue
            recent = [d for d in b["nudged"] if d >= (today - timedelta(days=6)).isoformat()]
            if len(recent) >= s.sales_nudges_week or today.isoformat() in recent:
                continue
            ov = await overview(user_id, business_id)
            if not ov or not ov["access"]["forecast"] or not (ov.get("slow") or {}).get("slow"):
                continue
            if ov["access"]["ideas"] in ("all", "weekly") and ov.get("ideas"):
                # a mission carries the day through (post, go-ahead, check-in, result) and sends
                # its own message instead of this alert: every slow day on Pro, and on Plus the
                # day this week's idea is still unused (going ahead records it as used)
                from harness.missions import slow_day
                if await slow_day.consider(user_id, b, ov):
                    await asyncio.to_thread(db.update, user_id, business_id, nudged=(recent + [today.isoformat()])[-10:])
                    sent += 1
                    continue
            f = ov["forecast"]
            idea = (ov.get("ideas") or [None])[0]
            body = (f"Tomorrow looks slow for {b['name']}: about ₹{f['value']:,}"
                    + (f", under your break-even of ₹{ov['slow']['breakeven']:,}" if ov["slow"].get("breakeven") else "")
                    + (f". Idea: {idea['title']}. Tap to make the post." if idea else ". Tap to see why."))
            from harness import push
            await push.send(user_id, "How's business", body, url="/business", tag=f"business-{business_id}-{today}")
            if ov["access"]["whatsapp"]:
                try:
                    from harness.whatsapp import service as wa
                    await wa.notify(user_id, "reminder", body, title="How's business")
                except Exception as e:  # noqa: BLE001
                    log.warning("sales: whatsapp alert failed", error=str(e)[:200])
            await asyncio.to_thread(db.update, user_id, business_id, nudged=(recent + [today.isoformat()])[-10:])
            sent += 1
        except Exception as e:  # noqa: BLE001 - one business must not stop the others
            log.warning("sales: evening alert failed", business_id=business_id, error=str(e)[:200])
    if len(_checked) > 10_000:
        _checked.clear()
    return sent
