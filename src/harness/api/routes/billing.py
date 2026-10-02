"""GET /billing, POST /billing/checkout, POST /billing/portal (JWT) and
POST /billing/webhook (authenticated by Dodo's Standard Webhooks signature,
never by a JWT)."""

import asyncio
import json
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from harness.api.auth import get_current_user
from harness.billing import dodo
from harness.billing.entitlements import billing_enabled, standing
from harness.billing.plans import PLANS
from harness.db import billing as billing_db
from harness.logging import log

router = APIRouter()


def _iso(dt) -> str | None:
    return dt.isoformat() if dt else None


@router.get("/billing")
async def billing(user: dict = Depends(get_current_user)) -> dict:
    plans = [p.to_dict() for p in PLANS.values()]
    if not billing_enabled():
        return {"enabled": False, "plan": "free", "plans": plans}
    st = await asyncio.to_thread(standing, user["user_id"])
    a = st.account
    return {
        "enabled": True,
        "plan": st.plan.id,
        "plan_label": st.plan.label,
        "status": a.plan_status,
        "period_start": _iso(st.period_start),
        "renews_at": _iso(a.plan_renews_at),
        "ends_at": _iso(a.plan_ends_at),
        "allowance_usd": st.plan.monthly_allowance_usd,
        "allowance_left_usd": float(max(st.allowance_left, 0)),
        "credits_usd": float(st.credits),
        "free_pool_exhausted": st.pool_exhausted,
        "has_portal": bool(a.billing_customer_id),
        "plans": plans,
    }


class CheckoutRequest(BaseModel):
    product: Literal["plus", "pro", "topup"]


@router.post("/billing/checkout")
async def checkout(req: CheckoutRequest, user: dict = Depends(get_current_user)) -> dict:
    try:
        url = await dodo.create_checkout(req.product, user["user_id"], user.get("email"))
    except dodo.BillingNotConfigured as e:
        raise HTTPException(status_code=503, detail=str(e))
    except httpx.HTTPError as e:
        log.warning("dodo checkout failed", error=str(e))
        raise HTTPException(status_code=502, detail="Could not start checkout. Try again shortly.")
    return {"url": url}


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
