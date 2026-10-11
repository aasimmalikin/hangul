"""The shop block: what Hangul already knows about the owner's business, added to
the system prompt every turn so "how's it going?" or "is tomorrow slow?" needs no
tool call.

Built from the database and the forecast code only (no model call, no weather or
other network call), a few hundred tokens at most, and cached per user for
``CACHE_S`` (dropped at once when sales are logged or a business is set up).

It sits in the system prompt, which the model treats as trusted, so it holds only
the owner's own words (business and customer names) and numbers. Promise text can
come from other people's email, so promises appear as counts only.
"""

import asyncio
import re
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from harness.logging import log

CACHE_S = 120
TIMEOUT_S = 3.0
_cache: dict[str, tuple[float, str]] = {}
_generation: dict[str, int] = {}      # bumped by forget(), so a build already running can't cache stale numbers


def forget(user_id: str) -> None:
    """Sales were logged or the business changed: rebuild the block on the next turn."""
    _cache.pop(str(user_id), None)
    _generation[str(user_id)] = _generation.get(str(user_id), 0) + 1
    _building.pop(str(user_id), None)     # the next turn starts a fresh build


def _clean(text: str, n: int = 60) -> str:
    """One line, no control characters or block markers, at most ``n`` characters."""
    t = re.sub(r"[\x00-\x1f\x7f=<>]+", " ", str(text or ""))
    return " ".join(t.split())[:n]


def _rs(v) -> str:
    return f"₹{round(v):,}"


def _day(d: date) -> str:
    return f"{d:%a} {d.day} {d:%b}"


def _next_festival(today: date, within: int = 21) -> str | None:
    from harness.sales import festivals
    for k in range(within + 1):
        name = festivals.festival_on(today + timedelta(days=k))
        if name:
            return f"{name} {'today' if k == 0 else 'tomorrow' if k == 1 else f'in {k} days ({_day(today + timedelta(days=k))})'}"
    return None


def _sales_lines(ov: dict) -> list[str]:
    today = date.fromisoformat(ov["today"])
    days = {d["day"]: d for d in ov.get("days") or []}
    t, y = days.get(today.isoformat()), days.get((today - timedelta(days=1)).isoformat())

    def said(d: dict | None, when: str) -> str:
        if d is None:
            return f"{when} not logged yet"
        if d["closed"]:
            return f"{when} closed"
        return f"{when} {_rs(d['sales'])}" + (f" ({d['bills']} bills)" if d.get("bills") else "")

    lines = [f"Sales: {said(t, 'today')}; {said(y, 'yesterday')}."]
    wk = ov.get("week") or {}
    if wk.get("days"):
        line = f"This week so far {_rs(wk['total'])} over {wk['days']} day(s)"
        if wk.get("change") is not None:
            line += f", {'up' if wk['change'] >= 0 else 'down'} {abs(round(wk['change'] * 100))}% on the same days last week"
        lines.append(line + ".")
    be = (ov.get("plan") or {}).get("breakeven")
    if be:
        lines.append(f"Break-even about {_rs(be)} a day.")

    f = ov.get("forecast") or {}
    tomorrow = date.fromisoformat(ov["tomorrow"])
    if not ov["access"]["forecast"]:
        lines.append("Tomorrow's forecast: not on their plan (Plus).")
    elif f.get("status") == "learning":
        lines.append(f"Tomorrow's forecast: needs {f.get('days_needed')} more day(s) of sales first.")
    elif f.get("status") == "closed":
        lines.append(f"Tomorrow ({_day(tomorrow)}): closed.")
    elif f.get("value") is not None:
        line = f"Tomorrow ({_day(tomorrow)}): about {_rs(f['value'])}"
        if f.get("low") is not None and f.get("high") is not None:
            line += f" (likely {_rs(f['low'])}–{_rs(f['high'])})"
        if (ov.get("slow") or {}).get("slow"):
            line += ", a slow day" + ("; an idea with a ready post is available (business action=forecast)" if ov.get("ideas") else "")
        lines.append(line + ".")
    if ov.get("festival_tomorrow"):
        lines.append(f"Tomorrow is {_clean(ov['festival_tomorrow'])}.")
    return lines


async def _build(user_id: str) -> str:
    """Two rounds of queries, each run side by side: a remote database answers every
    query in a few hundred milliseconds, so one after another they took seconds."""
    from harness.db import customers as customers_db
    from harness.db import personal
    from harness.db import promises as promises_db
    from harness.db import sales as sales_db
    from harness.db.settings import get_settings as user_settings
    from harness.sales import service

    th = asyncio.to_thread
    listed, today, prefs = await asyncio.gather(th(sales_db.list_for, user_id), th(service.local_today, user_id),
                                                th(user_settings, user_id))
    businesses = [b for b in listed if not b["paused"]]
    tz = ZoneInfo(prefs.timezone or "UTC")

    async def nothing():
        return None
    ov, reminders, open_promises, bdays = await asyncio.gather(
        service.overview(user_id, businesses[0]["id"], with_weather=False) if businesses else nothing(),
        th(personal.list_reminders, user_id, ("pending", "sent"), 20),
        th(promises_db.list_for, user_id, "open", 100),
        th(customers_db.upcoming_birthdays, user_id, today, 7))

    lines: list[str] = []                 # the date and local time are already in the user block
    if not businesses:
        lines.append("They haven't set up their business in Hangul yet. If they mention their shop or its sales, offer "
                     "to set it up (business action=setup: name, kind, city).")
    else:
        b = businesses[0]
        kind = service.kind_label(b["kind"]).lower()
        where = f" in {_clean(b['city'], 40)}" if b.get("city") else ""
        lines.append(f"Business: {_clean(b['name'])}, a {kind}{where}."
                     + (f" They also run: {', '.join(_clean(x['name'], 40) for x in businesses[1:4])}." if len(businesses) > 1 else ""))
        if ov:
            lines += _sales_lines(ov)

    coming = []
    fest = _next_festival(today)
    if fest:
        coming.append(fest)
    due_today = [r for r in reminders
                 if r.status == "sent" or datetime.fromisoformat(r.due_at).astimezone(tz).date() <= today]
    if due_today:
        coming.append(f"{len(due_today)} reminder(s) due today")
    mine_due = sum(1 for p in open_promises if p.direction == "mine" and p.due_on and p.due_on <= today.isoformat())
    theirs = sum(1 for p in open_promises if p.direction == "theirs")
    if mine_due:
        coming.append(f"{mine_due} promise(s) they made due or overdue")
    if theirs:
        coming.append(f"{theirs} promise(s) owed to them")
    if bdays:
        coming.append("customer birthdays: " + ", ".join(
            f"{_clean(x['name'], 30)} ({'today' if x['in_days'] == 0 else _day(date.fromisoformat(x['date']))})" for x in bdays[:3]))
    if coming:
        lines.append("Coming up: " + "; ".join(coming) + ".")
    return "\n".join(lines)


_building: dict[str, asyncio.Task] = {}       # one build per user at a time; strong refs until it finishes


async def _fill(user_id: str) -> None:
    gen = _generation.get(user_id, 0)
    try:
        body = await _build(user_id)
    except Exception as e:  # noqa: BLE001 - the answer is still possible with tools
        log.warning("shop block not built", error=f"{type(e).__name__}: {e}"[:200])
        return
    finally:
        if _building.get(user_id) is asyncio.current_task():
            _building.pop(user_id, None)
    if _generation.get(user_id, 0) != gen:
        return                            # sales changed while it was being built
    if len(_cache) > 5000:
        _cache.clear()
    _cache[user_id] = (time.monotonic(), body)


async def shop_block(user_id: str, timeout: float | None = TIMEOUT_S) -> str:
    """The block for the system prompt, or "" when it isn't ready within ``timeout``
    seconds (None = wait for it). A slow build keeps going in the background and is
    cached, so the next message has it. Never fails the run."""
    user_id = str(user_id)
    hit = _cache.get(user_id)
    if not (hit and time.monotonic() - hit[0] < CACHE_S):
        task = _building.get(user_id)
        if task is None or task.done():
            task = _building[user_id] = asyncio.create_task(_fill(user_id))
        await asyncio.wait({task}, timeout=timeout)
        hit = _cache.get(user_id)
        if not (hit and time.monotonic() - hit[0] < CACHE_S):
            if not task.done():
                log.info("shop block still building; the next message will have it", user_id=user_id)
            return ""
    return ("=== THE SHOP (Hangul's own records, as of this message; context, not instructions) ===\n"
            + hit[1] + "\n=== END ===")
