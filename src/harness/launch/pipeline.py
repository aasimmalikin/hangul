"""Building a launch plan's live parts in the background.

Fixed stages, not a free-running agent: prices (the most expensive items
first, up to ``launch_max_searches`` with the benchmarks), then industry
benchmarks, then nearby suppliers. Each stage is saved as it finishes, so a
failure later keeps what was found. The whole build is one meter: its
searches and extraction calls are settled as one ledger entry when it ends,
and the total is kept on the plan. A push notification says when it's ready.

Runs inside the API process (like the scheduler); a build whose process dies
shows as failed after ``db.launch.STALE_S`` and can be started again.
"""

import asyncio
from dataclasses import dataclass

from harness.config import get_settings
from harness.db import launch as db
from harness.launch import plan as planner
from harness.launch import sourcing
from harness.logging import log

_tasks: set[asyncio.Task] = set()      # keep references so builds aren't garbage-collected


@dataclass
class Access:
    allowed: bool
    reason: str | None = None          # plan_required | launch_quota | insufficient_balance
    detail: str = ""
    plan_needed: str | None = None
    left: int | None = None            # sourced plans left this month (None = no limit)

    def as_dict(self) -> dict:
        return {"allowed": self.allowed, "reason": self.reason, "detail": self.detail,
                "plan_needed": self.plan_needed, "left": self.left}


def access(user_id: str) -> Access:
    """May this user start a sourced plan now? (Estimate-only plans are always allowed.)"""
    from harness.billing import entitlements
    from harness.billing.plans import get_plan
    if not entitlements.billing_enabled():
        return Access(True)
    st = entitlements.standing(user_id)
    plan = st.plan
    if plan.launch_sourced_month <= 0:
        return Access(False, "plan_required", "Live prices and sellers are part of the Plus and Pro plans. "
                      "On Free, plans use Hangul's estimates, which you can edit.", "plus", 0)
    used = db.sourced_this_month(user_id)
    left = max(0, plan.launch_sourced_month - used)
    if left <= 0:
        nxt = "pro" if plan.id == "plus" else None
        more = f" Pro includes {get_plan('pro').launch_sourced_month} a month." if nxt else ""
        return Access(False, "launch_quota", f"You've used this month's {plan.launch_sourced_month} plan(s) with live "
                      f"prices.{more} This one uses Hangul's estimates.", nxt, 0)
    if not st.can_spend:
        return Access(False, "insufficient_balance", "Your plan's usage for this period is used up, so this plan uses "
                      "Hangul's estimates. Add credits to search live prices.", None, left)
    return Access(True, left=left)


async def _build(user_id: str, plan_id: int, only: list[str] | None = None) -> None:
    from harness.billing import meter
    s = get_settings()
    p = await asyncio.to_thread(db.get, user_id, plan_id)
    if p is None:
        return
    async with meter.metering(user_id, settle_on_exit=True) as m:
        try:
            await asyncio.wait_for(_stages(user_id, p, only, s.launch_max_searches), timeout=s.launch_build_timeout_s)
            await asyncio.to_thread(db.update, user_id, plan_id, status="ready", error="",
                                    progress={"stage": "done", "done": 1, "total": 1})
        except Exception as e:  # noqa: BLE001 - the plan keeps what was found
            log.warning("launch: build failed", plan_id=plan_id, error=f"{type(e).__name__}: {str(e)[:200]}")
            await asyncio.to_thread(db.update, user_id, plan_id, status="failed",
                                    error="Some prices couldn't be checked. What was found is kept; try again later.")
        finally:
            await asyncio.to_thread(db.add_cost, user_id, plan_id, m.extra)
    if only is None:
        fresh = await asyncio.to_thread(db.get, user_id, plan_id)
        if fresh is not None:
            from harness import push
            e = fresh["economics"]
            await push.send(user_id, "Your launch plan is ready",
                            f"{fresh['title']}: about ₹{e['startup_total']:,} to start, break-even at "
                            f"{e['breakeven_per_day'] or '—'} {kind_unit(fresh['kind'])}s a day.",
                            url=f"/launch/{plan_id}", tag=f"launch-{plan_id}")


def kind_unit(kind: str) -> str:
    from harness.launch import kinds
    k = kinds.get(kind)
    return k.unit if k else "sale"


async def _stages(user_id: str, p: dict, only: list[str] | None, max_searches: int) -> None:
    plan_id, city, area = p["id"], p["city"], p["area"]
    items = p["items"]
    if only is not None:
        chosen = [it for it in items if it["key"] in only]
    else:
        chosen = planner.to_source(items, max_searches - len(p["benchmarks"]))
    total = len(chosen)

    # 1. prices, a few items at a time so the page shows progress
    done = 0
    for i in range(0, len(chosen), sourcing.BATCH * 2):
        part = chosen[i:i + sourcing.BATCH * 2]
        found = {it["key"]: it for it in await sourcing.source_items(part, city)}
        latest = await asyncio.to_thread(db.get, user_id, plan_id)
        if latest is None:
            return
        # merge onto the latest items: the user may have edited some meanwhile
        merged = []
        for it in latest["items"]:
            new = found.get(it["key"])
            if new is None:
                merged.append(it)
            elif it.get("status") == "user":
                merged.append({**new, "amount": it["amount"], "qty": it["qty"], "include": it["include"], "status": "user"})
            else:
                merged.append({**new, "qty": it["qty"], "include": it["include"]})
        done += len(part)
        await asyncio.to_thread(db.update, user_id, plan_id, items=merged,
                                progress={"stage": "prices", "done": done, "total": total})
    if only is not None:
        return

    # 2. industry figures
    await asyncio.to_thread(db.update, user_id, plan_id, progress={"stage": "benchmarks", "done": 0, "total": 1})
    benchmarks = await sourcing.source_benchmarks(p["benchmarks"], city)
    await asyncio.to_thread(db.update, user_id, plan_id, benchmarks=benchmarks)

    # 3. nearby suppliers (OpenStreetMap)
    queries = planner.local_queries(items)
    if queries:
        await asyncio.to_thread(db.update, user_id, plan_id, progress={"stage": "suppliers", "done": 0, "total": 1})
        suppliers = await sourcing.local_suppliers(queries, city, area)
        await asyncio.to_thread(db.update, user_id, plan_id, suppliers=suppliers)


def start(user_id: str, plan_id: int, only: list[str] | None = None) -> asyncio.Task:
    """Run the build in the background (the caller has already marked it sourcing)."""
    t = asyncio.create_task(_build(user_id, plan_id, only))
    _tasks.add(t)
    t.add_done_callback(_tasks.discard)
    return t


async def create(user_id: str, answers: dict, *, live: bool = True,
                 conversation_id: str | None = None) -> tuple[dict, Access]:
    """Save a new plan from the answers (raises planner.BadAnswer) and, when the
    user may, start sourcing it. Returns (plan, access)."""
    fields = planner.new_plan(**answers)
    p = await asyncio.to_thread(db.create, user_id, fields, conversation_id)
    if not live:
        return p, Access(False, "not_asked")
    acc = await asyncio.to_thread(access, user_id)
    if acc.allowed:
        p = await begin(user_id, p["id"]) or p
    return p, acc


async def begin(user_id: str, plan_id: int) -> dict | None:
    """Mark a saved plan as sourcing and start the build; None if it already is."""
    p = await asyncio.to_thread(db.get, user_id, plan_id)
    if p is None:
        return None
    total = len(planner.to_source(p["items"], get_settings().launch_max_searches - len(p["benchmarks"])))
    marked = await asyncio.to_thread(db.start_sourcing, user_id, plan_id, total)
    if marked is not None:
        start(user_id, plan_id)
    return marked
