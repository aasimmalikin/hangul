"""GET /billing, POST /billing/checkout, POST /billing/portal (JWT) and
POST /billing/webhook (authenticated by Dodo's Standard Webhooks signature,
never by a JWT)."""

import asyncio
import json
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from harness.api.auth import get_current_user
from harness.billing import dodo
from harness.billing.entitlements import TRIAL_STATUSES, billing_enabled, messages_for, standing
from harness.billing.plans import PLANS, RECOMMENDED, prices_for, product_key, region_for_timezone
from harness.db import billing as billing_db
from harness.logging import log

router = APIRouter()


def _iso(dt) -> str | None:
    return dt.isoformat() if dt else None


# Show the upgrade nudge once this share of the period's allowance is used.
NUDGE_AT = 0.8


def trial_days_for(account, product: str) -> int:
    """Days of free trial this checkout gets: Plus only, once per account (one
    that has never had a subscription), and 0 when billing_trial_days is 0."""
    from harness.config import get_settings
    days = get_settings().billing_trial_days
    if product != "plus" or days <= 0 or account.plan != "free" or account.billing_subscription_id:
        return 0
    return days


def offer_region(user_id: str) -> str:
    """Which prices to offer: Indian ones when the user's (device-following)
    timezone is India's, and only if the Indian Plus product is set up."""
    from harness.db.settings import get_settings as user_settings
    try:
        region = region_for_timezone(user_settings(user_id).timezone)
    except Exception:  # noqa: BLE001 - no settings row: international prices
        return "intl"
    return region if region == "intl" or dodo.product_id_for("plus_in") else "intl"


def recommended_plan(user_id: str) -> str | None:
    """The plan suggested for the user's persona (None until they pick one)."""
    from harness.db.settings import get_settings as user_settings
    try:
        return RECOMMENDED.get(user_settings(user_id).persona or "")
    except Exception:  # noqa: BLE001 - no settings row: no suggestion
        return None


def _plans_for(region: str) -> list[dict]:
    """Each plan with its price (monthly and yearly) and allowance at ``region``'s prices."""
    out = []
    for p in PLANS.values():
        d = p.to_dict()
        d["monthly_allowance_usd"] = p.allowance_usd(region)
        d["prices"] = prices_for(p.id, region)
        # yearly is only offered once its Dodo product exists
        if p.id != "free" and not dodo.product_id_for(product_key(p.id, region, "year")):
            d["prices"].pop("year", None)
        out.append(d)
    return out


def public_region(tz: str) -> str:
    """offer_region for a visitor with no account: the device's timezone, and
    Indian prices only when the Indian Plus product is set up, so the homepage
    never shows a price that checkout wouldn't charge."""
    region = region_for_timezone(tz)
    return region if region == "intl" or dodo.product_id_for("plus_in") else "intl"


@router.get("/billing/prices")
async def public_prices(tz: str = "") -> dict:
    """Plans and prices for the signed-out homepage, for the visitor's region
    (from their device timezone). Public: nothing personal goes in or out."""
    from harness.config import get_settings
    region = public_region(tz[:64])
    return {"region": region, "trial_days": max(get_settings().billing_trial_days, 0), "plans": _plans_for(region)}


@router.get("/billing")
async def billing(user: dict = Depends(get_current_user)) -> dict:
    region = await asyncio.to_thread(offer_region, user["user_id"])
    plans = _plans_for(region)
    recommended = await asyncio.to_thread(recommended_plan, user["user_id"])
    if not billing_enabled():
        return {"enabled": False, "plan": "free", "plans": plans, "recommended_plan": recommended}
    st = await asyncio.to_thread(standing, user["user_id"])
    a = st.account
    allowance = float(st.allowance)
    left = float(max(st.allowance_left, 0))
    used_share = 1 - left / allowance if allowance > 0 else 1.0
    messages_left, messages_total = await asyncio.to_thread(lambda: (messages_for(left), messages_for(allowance)))
    trialing = a.plan_status in TRIAL_STATUSES
    brands = await asyncio.to_thread(_brand_summary, user["user_id"], region)
    return {
        "enabled": True,
        # brand slots: the plan's + bought; the price of one more (only when it can be bought)
        "brands": brands,
        "plan": st.plan.id,
        "plan_label": st.plan.label,
        "status": a.plan_status,
        "period_start": _iso(st.period_start),
        "renews_at": _iso(a.plan_renews_at),
        "ends_at": _iso(a.plan_ends_at),
        "allowance_usd": allowance,
        "allowance_left_usd": left,
        # what people understand: "about 140 messages left" (allowance / average cost of a run)
        "messages_left": messages_left,
        "messages_total": messages_total,
        # the chat shows the upgrade card from here on, before the allowance runs out
        "nudge": st.plan.id != "pro" and used_share >= NUDGE_AT and not st.credits > 0,
        "trialing": trialing,
        "trial_ends_at": _iso(a.plan_renews_at or a.plan_ends_at) if trialing else None,
        "trial_days": trial_days_for(a, "plus"),
        "credits_usd": float(st.credits),
        "free_pool_exhausted": st.pool_exhausted,
        "has_portal": bool(a.billing_customer_id),
        "region": region,                         # prices offered: "in" (₹) or "intl" ($)
        "plan_region": a.plan_region,             # what the current plan was bought at
        "plan_interval": a.plan_interval,
        "recommended_plan": recommended,          # from the persona: "Recommended for you" on that plan
        "plans": plans,
    }


def _brand_summary(user_id: str, region: str) -> dict | None:
    """{slots, used, slot_price}: the plan's + bought brand slots, and the price
    of one more when it can be bought. None if it can't be read right now."""
    from harness.billing.plans import PRICES
    from harness.db import brands as brands_db
    try:
        slots = brands_db.slots(user_id)
        used = len(brands_db.list_for(user_id, slots))
    except Exception as e:  # noqa: BLE001 - the rest of the billing page still shows
        log.warning("brand slots not read", error=str(e)[:200])
        return None
    slot_region = "in" if region == "in" and dodo.product_id_for("brand_slot_in") else "intl"
    product = "brand_slot_in" if slot_region == "in" else "brand_slot"
    price = PRICES[("brand_slot", slot_region, "once")].to_dict() if dodo.product_id_for(product) else None
    return {"slots": slots, "used": used, "slot_price": price}


class CheckoutRequest(BaseModel):
    product: Literal["plus", "pro", "topup", "brand_slot"]
    interval: Literal["month", "year"] = "month"


def checkout_product(product: str, interval: str, region: str) -> str:
    """The Dodo product to sell: the regional / yearly variant when it is set
    up, else the closest one that is (yearly -> monthly, Indian -> international)."""
    if product == "topup":
        return "topup"
    if product == "brand_slot":
        return "brand_slot_in" if region == "in" and dodo.product_id_for("brand_slot_in") else "brand_slot"
    for r, i in ((region, interval), (region, "month"), ("intl", interval), ("intl", "month")):
        key = product_key(product, r, i)
        if dodo.product_id_for(key):
            return key
    return product


@router.post("/billing/checkout")
async def checkout(req: CheckoutRequest, user: dict = Depends(get_current_user)) -> dict:
    account = await asyncio.to_thread(billing_db.get_account, user["user_id"])
    trial_days = trial_days_for(account, req.product)
    region = await asyncio.to_thread(offer_region, user["user_id"])
    sold = checkout_product(req.product, req.interval, region)
    try:
        url = await dodo.create_checkout(sold, user["user_id"], user.get("email"), trial_days=trial_days)
    except dodo.BillingNotConfigured as e:
        raise HTTPException(status_code=503, detail=str(e))
    except httpx.HTTPError as e:
        log.warning("dodo checkout failed", error=str(e))
        raise HTTPException(status_code=502, detail="Could not start checkout. Try again shortly.")
    return {"url": url, "trial_days": trial_days, "product": sold}


@router.post("/billing/portal")
async def portal(user: dict = Depends(get_current_user)) -> dict:
    account = await asyncio.to_thread(billing_db.get_account, user["user_id"])
    if not account.billing_customer_id:
        raise HTTPException(status_code=404, detail="No subscription to manage yet.")
    try:
        url = await dodo.portal_link(account.billing_customer_id)
    except dodo.BillingNotConfigured as e:
        raise HTTPException(status_code=503, detail=str(e))
    except httpx.HTTPError as e:
        log.warning("dodo portal failed", error=str(e))
        raise HTTPException(status_code=502, detail="Could not open the billing portal. Try again shortly.")
    return {"url": url}


REASONS = ("too_expensive", "not_using", "missing_feature", "not_working", "switching", "other")


class LeaveRequest(BaseModel):
    reason: Literal["too_expensive", "not_using", "missing_feature", "not_working", "switching", "other"]
    detail: str = Field(default="", max_length=1000)
    action: Literal["keep", "downgrade", "cancel"]


@router.post("/billing/leave")
async def leave(req: LeaveRequest, user: dict = Depends(get_current_user)) -> dict:
    """The "Before you go" flow's last step. Whatever the user chooses is
    recorded with their reason. Cancelling is one call: the plan stays until
    the end of the paid period, and "Keep my plan" (/billing/resume) undoes it."""
    from datetime import datetime, timezone
    uid = user["user_id"]
    account = await asyncio.to_thread(billing_db.get_account, uid)
    if account.plan == "free" or not account.billing_subscription_id:
        raise HTTPException(status_code=409, detail="There's no paid plan to change.")
    detail = req.detail.strip()
    try:
        if req.action == "keep":
            outcome, result = "kept", {"plan": account.plan}
        elif req.action == "downgrade":
            if account.plan != "pro":
                raise HTTPException(status_code=409, detail="Only Pro can switch down to Plus.")
            await dodo.change_plan(account.billing_subscription_id, "plus")
            await asyncio.to_thread(billing_db.update_account, uid, plan="plus", plan_period_start=datetime.now(timezone.utc))
            outcome, result = "downgraded", {"plan": "plus"}
        else:
            await dodo.set_cancel_at_period_end(account.billing_subscription_id, True,
                                                f"{req.reason}: {detail}" if detail else req.reason)
            ends = account.plan_renews_at or account.plan_ends_at
            await asyncio.to_thread(billing_db.update_account, uid, plan_status="cancelling", plan_ends_at=ends, plan_renews_at=None)
            outcome, result = "cancelled", {"plan": account.plan, "ends_at": _iso(ends)}
    except dodo.BillingNotConfigured as e:
        raise HTTPException(status_code=503, detail=str(e))
    except httpx.HTTPError as e:
        log.warning("dodo subscription change failed", action=req.action, error=str(e))
        raise HTTPException(status_code=502, detail="Couldn't reach the payment service. Try again in a moment.")
    await asyncio.to_thread(billing_db.record_churn, uid, plan=account.plan, reason=req.reason, detail=detail, outcome=outcome)
    return {"outcome": outcome, **result}


@router.post("/billing/resume")
async def resume(user: dict = Depends(get_current_user)) -> dict:
    """Undo a cancellation before the period ends: the plan simply continues."""
    uid = user["user_id"]
    account = await asyncio.to_thread(billing_db.get_account, uid)
    if account.plan_status != "cancelling" or not account.billing_subscription_id:
        raise HTTPException(status_code=409, detail="Your plan isn't set to end.")
    try:
        await dodo.set_cancel_at_period_end(account.billing_subscription_id, False)
    except httpx.HTTPError as e:
        log.warning("dodo resume failed", error=str(e))
        raise HTTPException(status_code=502, detail="Couldn't reach the payment service. Try again in a moment.")
    await asyncio.to_thread(billing_db.update_account, uid, plan_status="active",
                            plan_renews_at=account.plan_ends_at, plan_ends_at=None)
    return {"plan": account.plan, "status": "active"}


@router.post("/billing/webhook")
async def webhook(request: Request) -> dict:
    raw = await request.body()
    h = request.headers
    webhook_id = h.get("webhook-id")
    if not dodo.verify_signature(raw, webhook_id, h.get("webhook-timestamp"), h.get("webhook-signature")):
        raise HTTPException(status_code=401, detail="bad signature")
    try:
        payload = json.loads(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid JSON")
    kind = payload.get("type", "")
    if not await asyncio.to_thread(billing_db.claim_event, webhook_id, kind):
        return {"ok": True, "result": "duplicate"}
    try:
        result = await asyncio.to_thread(dodo.apply_event, payload)
    except Exception as e:  # noqa: BLE001
        # let Dodo's retry reapply it
        await asyncio.to_thread(billing_db.release_event, webhook_id)
        log.error("billing webhook failed", event_type=kind, error=str(e))
        raise HTTPException(status_code=500, detail="webhook handling failed")
    log.info("billing webhook", event_type=kind, result=result)
    return {"ok": True, "result": result}
