"""Dodo Payments: hosted checkout, the customer portal, and the webhook that
applies them.

Dodo is the merchant of record -- it takes the payment, handles VAT / GST /
sales tax, and hosts the portal where users manage their subscription -- so
this module never sees a card. It (1) asks for a checkout URL carrying our
``user_id`` as metadata, (2) mints portal links on demand, and (3) turns
signed webhook events into plan / credit changes.

The API key is read here, in the billing routes' code path, never by a tool.
"""

import base64
import hashlib
import hmac
import time
from datetime import datetime, timezone
from decimal import Decimal

import httpx

from harness.config import get_settings
from harness.db import billing as billing_db
from harness.db import ledger
from harness.logging import log

PRODUCTS = ("plus", "pro", "topup",
            # yearly and Indian (INR) variants of the plans: see plans.product_key
            "plus_annual", "pro_annual", "plus_in", "pro_in", "plus_in_annual", "pro_in_annual")

# Subscription statuses that keep the paid plan. A user who cancels stays
# `active` with cancel_at_next_billing_date until the period ends; then Dodo
# sends `subscription.expired` / `subscription.cancelled`.
ACTIVE_STATUSES = {"active", "past_due"}

# Standard Webhooks: reject deliveries this far from now (replay protection).
TOLERANCE_S = 5 * 60


class BillingNotConfigured(RuntimeError):
    pass


def api_base() -> str:
    return "https://test.dodopayments.com" if get_settings().dodo_test_mode else "https://live.dodopayments.com"


def product_id_for(product: str) -> str | None:
    return getattr(get_settings(), f"dodo_product_{product}", None)


def product_for_id(product_id) -> str | None:
    if not product_id:
        return None
    return next((p for p in PRODUCTS if product_id_for(p) == str(product_id)), None)


def _headers() -> dict:
    key = get_settings().dodo_api_key
    if not key:
        raise BillingNotConfigured("Dodo Payments is not configured.")
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


async def create_checkout(product: str, user_id: str, email: str | None, *, trial_days: int = 0) -> str:
    """A checkout URL for ``product``; raises BillingNotConfigured. With
    ``trial_days`` the subscription starts as a trial: Dodo authorises the
    card for $0 now and takes the first real charge when the trial ends."""
    s = get_settings()
    pid = product_id_for(product)
    if not pid:
        raise BillingNotConfigured(f"No Dodo product configured for '{product}'.")
    body: dict = {
        "product_cart": [{"product_id": pid, "quantity": 1}],
        "return_url": s.billing_return_url,
        # copied onto the payment / subscription, so the webhook knows the user
        "metadata": {"user_id": str(user_id), "product": product},
    }
    if trial_days > 0 and product.split("_")[0] in ("plus", "pro"):
        body["subscription_data"] = {"trial_period_days": int(trial_days)}
        body["metadata"]["trial"] = "1"           # copied onto the subscription: the webhook marks it trialing
    if email:
        body["customer"] = {"email": email}
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(f"{api_base()}/checkouts", json=body, headers=_headers())
    r.raise_for_status()
    url = r.json().get("checkout_url")
    if not url:
        raise httpx.HTTPError("checkout created without a checkout_url")
    return url


async def portal_link(customer_id: str) -> str:
    """A short-lived link to Dodo's customer portal (cancel, change card, invoices)."""
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(f"{api_base()}/customers/{customer_id}/customer-portal/session",
                              params={"return_url": get_settings().billing_return_url}, headers=_headers())
    r.raise_for_status()
    return r.json()["link"]


async def _subscription(method: str, path: str, body: dict) -> dict:
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.request(method, f"{api_base()}/subscriptions/{path}", json=body, headers=_headers())
    r.raise_for_status()
    return r.json() if r.content else {}


async def set_cancel_at_period_end(subscription_id: str, cancel: bool, comment: str = "") -> dict:
    """Cancel at the end of the paid period (the plan stays until then), or
    undo that. Dodo then sends subscription.updated, which the webhook applies."""
    body: dict = {"cancel_at_next_billing_date": cancel}
    if cancel and comment:
        body["cancellation_comment"] = comment[:500]
    return await _subscription("PATCH", subscription_id, body)


async def change_plan(subscription_id: str, product: str) -> dict:
    """Switch to another plan now, crediting the unused part of the current one."""
    pid = product_id_for(product)
    if not pid:
        raise BillingNotConfigured(f"No Dodo product configured for '{product}'.")
    return await _subscription("POST", f"{subscription_id}/change-plan",
                               {"product_id": pid, "quantity": 1, "proration_billing_mode": "prorated_immediately"})


def verify_signature(raw: bytes, webhook_id: str | None, timestamp: str | None,
                     signature: str | None, *, now: float | None = None) -> bool:
    """Standard Webhooks: base64(HMAC-SHA256(key, f"{id}.{ts}.{body}")), where
    key is the base64 part of the ``whsec_`` secret; the header holds one or
    more space-separated ``v1,<sig>`` entries."""
    secret = get_settings().dodo_webhook_secret
    if not (secret and webhook_id and timestamp and signature):
        return False
    try:
        if abs((now or time.time()) - int(timestamp)) > TOLERANCE_S:
            return False
        key = base64.b64decode(secret.removeprefix("whsec_"))
    except ValueError:
        return False
    signed = f"{webhook_id}.{timestamp}.".encode() + raw
    expected = base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode()
    return any(hmac.compare_digest(expected, part.split(",", 1)[1])
               for part in signature.split() if part.startswith("v1,"))


def _ts(value) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _user_for(data: dict) -> str | None:
    """metadata.user_id first; then the subscription / customer we already
    linked; then the customer's email (Dodo may not copy metadata everywhere)."""
    uid = (data.get("metadata") or {}).get("user_id")
    if uid:
        return str(uid)
    customer = data.get("customer") or {}
    return (billing_db.user_for(subscription_id=data.get("subscription_id"),
                                customer_id=customer.get("customer_id"),
                                email=customer.get("email")))


def apply_event(payload: dict) -> str:
    """Apply one verified webhook payload. Returns what happened (for logs/tests)."""
    kind = payload.get("type", "")
    data = payload.get("data") or {}
    user_id = _user_for(data)
    if user_id is None:
        log.warning("billing webhook without a user", event=kind)
        return "ignored:no_user"

    if kind == "payment.succeeded":
        if data.get("subscription_id"):
            return "ignored:subscription_payment"     # the subscription.* events carry it
        topups = sum(int(i.get("quantity") or 1) for i in (data.get("product_cart") or [])
                     if product_for_id(i.get("product_id")) == "topup")
        if not topups:
            return "ignored:payment"
        credit = Decimal(str(get_settings().billing_topup_credit_usd)) * topups
        ledger.record_transaction(user_id=user_id, amount=credit, kind="topup",
                                  thread_id=f"dodo-{data.get('payment_id')}"[:32])
        return "topup"

    if kind.startswith("subscription."):
        from harness.billing.plans import parse_product_key
        status = data.get("status")
        product = product_for_id(data.get("product_id"))
        bought, region, interval = parse_product_key(product) if product and product != "topup" else (None, "intl", "month")
        plan = bought if bought in ("plus", "pro") and status in ACTIVE_STATUSES else "free"
        cancelling = bool(data.get("cancel_at_next_billing_date")) and plan != "free"
        before = billing_db.get_account(user_id)
        # a trial runs from subscription.active until the first real charge (subscription.renewed)
        trial = (plan != "free" and kind != "subscription.renewed"
                 and str((data.get("metadata") or {}).get("trial", "")) == "1"
                 and (before.plan == "free" or before.plan_status in ("trialing", "trial_cancelling")))
        customer = data.get("customer") or {}
        fields = dict(
            plan=plan,
            plan_status=(("trial_cancelling" if cancelling else "trialing") if trial
                         else "cancelling" if cancelling else status),
            plan_renews_at=None if cancelling else _ts(data.get("next_billing_date")),
            plan_ends_at=_ts(data.get("expires_at")) or (_ts(data.get("next_billing_date")) if cancelling else None),
            billing_customer_id=customer.get("customer_id") or before.billing_customer_id,
            billing_subscription_id=data.get("subscription_id") or before.billing_subscription_id,
        )
        if plan != "free":
            # which price it was bought at decides the allowance (Indian plans include less)
            fields.update(plan_region=region, plan_interval=interval)
        switched = plan != "free" and (region, interval) != (before.plan_region, before.plan_interval)
        if plan != before.plan or (switched and kind != "subscription.renewed"):
            # a new plan (or the same plan at another price: monthly -> yearly) starts a fresh allowance period
            fields["plan_period_start"] = datetime.now(timezone.utc) if plan != "free" else None
        elif kind == "subscription.renewed" and before.plan_status in ("trialing", "trial_cancelling"):
            # the trial converted: the first paid period starts now, with the full allowance
            fields["plan_period_start"] = datetime.now(timezone.utc)
        elif kind == "subscription.renewed":
            fields["plan_period_start"] = _ts(data.get("previous_billing_date")) or datetime.now(timezone.utc)
        billing_db.update_account(user_id, **fields)
        return "period_reset" if kind == "subscription.renewed" and plan == before.plan else f"plan:{plan}"

    return "ignored:event"
