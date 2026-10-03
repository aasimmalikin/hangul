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
from harness.billing.plans import PLANS
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


@router.get("/billing")
async def billing(user: dict = Depends(get_current_user)) -> dict:
    plans = [p.to_dict() for p in PLANS.values()]
    if not billing_enabled():
        return {"enabled": False, "plan": "free", "plans": plans}
    st = await asyncio.to_thread(standing, user["user_id"])
    a = st.account
    allowance = float(st.allowance)
    left = float(max(st.allowance_left, 0))
    used_share = 1 - left / allowance if allowance > 0 else 1.0
    messages_left, messages_total = await asyncio.to_thread(lambda: (messages_for(left), messages_for(allowance)))
    trialing = a.plan_status in TRIAL_STATUSES
    return {
        "enabled": True,
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
        "plans": plans,
    }


class CheckoutRequest(BaseModel):
    product: Literal["plus", "pro", "topup"]


@router.post("/billing/checkout")
async def checkout(req: CheckoutRequest, user: dict = Depends(get_current_user)) -> dict:
    account = await asyncio.to_thread(billing_db.get_account, user["user_id"])
    trial_days = trial_days_for(account, req.product)
    try:
        url = await dodo.create_checkout(req.product, user["user_id"], user.get("email"), trial_days=trial_days)
    except dodo.BillingNotConfigured as e:
        raise HTTPException(status_code=503, detail=str(e))
    except httpx.HTTPError as e:
        log.warning("dodo checkout failed", error=str(e))
        raise HTTPException(status_code=502, detail="Could not start checkout. Try again shortly.")
    return {"url": url, "trial_days": trial_days}


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
