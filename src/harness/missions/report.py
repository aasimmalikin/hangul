"""What the missions earned: the outcome ledger.

Each measured slow day is the day's sales against the forecast Hangul made
*before* the offer. Summed over a month this is an estimate, and it is worded
as one: the forecast has its own error (``accuracy``), which is why a single
day only counts as "worked" when it beats the top of the forecast's range.
Days the owner said no to, didn't log, or were closed aren't counted.

On the 1st of each month (from 9 am local, for three days in case the
scheduler was down) a ``monthly_report`` mission sends last month's summary to
every owner who had a slow-day mission in it.
"""

import asyncio
from datetime import UTC, date, datetime, timedelta

from harness.db import missions as db
from harness.logging import log
from harness.missions import engine
from harness.missions.engine import Ctx, done, skip
from harness.missions.tell import tell

KIND = "monthly_report"
SEND_FROM_HOUR = 9


def month_start(d: date) -> date:
    return d.replace(day=1)


def next_month(d: date) -> date:
    return (d.replace(day=28) + timedelta(days=4)).replace(day=1)


def prev_month(d: date) -> date:
    return month_start(month_start(d) - timedelta(days=1))


def _price(user_id: str) -> str | None:
    from harness.billing import entitlements
    if not entitlements.billing_enabled():
        return None
    from harness.billing.plans import PRICES
    from harness.db import billing as billing_db
    acct = billing_db.get_account(user_id)
    if acct.plan not in ("plus", "pro"):
        return None
    p = PRICES.get((acct.plan, acct.plan_region or "intl", "month"))
    return f"{acct.plan.title()} costs you {p.label}" if p else None


def summary(user_id: str, month: date) -> dict:
    start = month_start(month)
    ms = db.between(user_id, start, next_month(start))
    went = [m for m in ms if m["data"].get("approved") and not m["data"].get("undone")]
    measured = [m for m in went if (m["data"].get("outcome") or {}).get("lift") is not None]
    lift = sum(m["data"]["outcome"]["lift"] for m in measured)
    best = max(measured, key=lambda m: m["data"]["outcome"]["lift"], default=None)
    return {
        "month": start.isoformat(), "label": start.strftime("%B %Y"),
        "spotted": len(ms), "went_ahead": len(went), "on_their_own": sum(1 for m in went if m["data"].get("auto")),
        "measured": len(measured), "worked": sum(1 for m in measured if m["data"]["outcome"]["verdict"] == "worked"),
        "lift": round(lift), "price": _price(user_id),
        "best": ({"mission_id": best["id"], "idea": best["data"]["idea"]["title"], "day": best["target_day"],
                  "business": best["data"]["business_name"], "lift": best["data"]["outcome"]["lift"]}
                 if best and best["data"]["outcome"]["lift"] > 0 else None),
        "days": [{"mission_id": m["id"], "day": m["target_day"], "business": m["data"].get("business_name"),
                  "idea": (m["data"].get("idea") or {}).get("title"), "status": m["status"],
                  "outcome": m["data"].get("outcome")} for m in ms],
    }


def text(s: dict) -> str:
    month = s["label"].split()[0]
    lines = [f"*{month} with Hangul*", f"{s['spotted']} slow day{'s' if s['spotted'] != 1 else ''} spotted, "
             f"{s['went_ahead']} offer{'s' if s['went_ahead'] != 1 else ''} run"
             + (f" ({s['on_their_own']} on my own)" if s["on_their_own"] else "") + "."]
    if s["measured"]:
        if s["lift"] > 0:
            lines.append(f"On those days you sold about *₹{s['lift']:,} more* than I'd forecast without the offers "
                         f"(an estimate: my forecasts have their own error).")
        else:
            lines.append(f"On those days sales came in about ₹{abs(s['lift']):,} under my forecasts overall, "
                         "so I'll lean on different ideas.")
        if s["best"]:
            b = s["best"]
            lines.append(f"Best: *{b['idea']}* on {date.fromisoformat(b['day']).strftime('%a %d %b')}, +₹{b['lift']:,}.")
    else:
        lines.append("No days were logged after the offers, so I couldn't measure them. Log your sales and I'll tell you what worked.")
    if s["price"]:
        lines.append(f"{s['price']} a month.")
    return "\n".join(lines)


async def _send(ctx: Ctx) -> engine.Outcome:
    month = date.fromisoformat(ctx.data["month"])
    s = await asyncio.to_thread(summary, ctx.user_id, month)
    if not s["spotted"]:
        return skip("Nothing to report.", report=s)
    await tell(ctx.user_id, text(s), url=f"/missions?month={s['month'][:7]}", tag=f"mission-report-{s['month'][:7]}",
               title="Your month")
    return done("Sent.", report=s)


TEMPLATE = engine.register(engine.Template(KIND, [("send", "Send {label}'s summary")], {"send": _send}))


async def due() -> int:
    """Start this month's report for every owner who had slow-day missions last month."""
    from harness.missions import allowed
    from harness.missions.slow_day import _local
    sent = 0
    utc_guess = datetime.now(UTC).date()
    for user_id in await asyncio.to_thread(db.users_with, "slow_day", prev_month(utc_guess) - timedelta(days=1)):
        try:
            today, hour = await asyncio.to_thread(_local, user_id)
            if today.day > 3 or (today.day == 1 and hour < SEND_FROM_HOUR):
                continue
            first = month_start(today)
            if await asyncio.to_thread(db.exists, user_id, KIND, first):
                continue
            if not await asyncio.to_thread(allowed, user_id):
                continue
            last = prev_month(today)
            got = await engine.begin(user_id, KIND, first, {"month": last.isoformat(), "label": last.strftime("%B")})
            sent += got is not None
        except Exception as e:  # noqa: BLE001
            log.warning("monthly report failed", user_id=user_id, error=str(e)[:200])
    return sent
