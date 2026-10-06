"""Paid model access (harness.billing): the plan decides which models,
efforts and modes a run may use, the allowance and credits decide whether it
may run at all, and only a correctly signed Dodo Payments webhook changes
either.

Runs against fakes: no Postgres, no Dodo Payments.
"""
import base64
import hashlib
import hmac
import json
import time
from decimal import Decimal

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from harness.api.auth import get_current_user
from harness.api.routes import ask_stream as stream_route
from harness.api.routes import billing as billing_route
from harness.api.routes import models as models_route
from harness.billing import entitlements
from harness.db import billing as billing_db
from harness.db import ledger
from harness.db.billing import Account
from tests.unit.test_resilience_backend import approve_app, pending_checkpoint  # noqa: F401

SECRET = "whsec_" + base64.b64encode(b"test-signing-key").decode()


@pytest.fixture
def billing(monkeypatch):
    """Billing switched on, with an in-memory account + ledger per user."""
    monkeypatch.setenv("DODO_API_KEY", "dodo_test")
    monkeypatch.setenv("DODO_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("DODO_PRODUCT_PLUS", "pdt_plus")
    monkeypatch.setenv("DODO_PRODUCT_PRO", "pdt_pro")
    monkeypatch.setenv("DODO_PRODUCT_TOPUP", "pdt_topup")
    monkeypatch.setenv("MODEL", "gpt-5.5")          # a frontier default, as in prod
    monkeypatch.setenv("DEFAULT_EFFORT", "medium")

    state = {"accounts": {}, "usage": {}, "credits": {}, "events": set(), "tx": []}

    def get_account(uid):
        return state["accounts"].get(uid, Account(user_id=uid))

    def update_account(uid, **fields):
        a = get_account(uid)
        for k, v in fields.items():
            setattr(a, k, v)
        state["accounts"][uid] = a
        return True

    def claim_event(eid, name):
        if eid in state["events"]:
            return False
        state["events"].add(eid)
        return True

    def record_transaction(user_id, amount, kind, thread_id=None):
        state["tx"].append((user_id, amount, kind))
        if kind == "topup":
            state["credits"][user_id] = state["credits"].get(user_id, Decimal(0)) + amount
        return amount

    monkeypatch.setattr(billing_db, "get_account", get_account)
    monkeypatch.setattr(billing_db, "update_account", update_account)
    monkeypatch.setattr(billing_db, "claim_event", claim_event)
    monkeypatch.setattr(billing_db, "release_event", lambda eid: state["events"].discard(eid))
    monkeypatch.setattr(billing_db, "user_for", lambda **kw: None)
    monkeypatch.setattr(ledger, "period_usage", lambda uid, since: state["usage"].get(uid, Decimal(0)))
    monkeypatch.setattr(ledger, "credit_balance", lambda uid: state["credits"].get(uid, Decimal(0)))
    state["pool_spent"] = Decimal(0)
    monkeypatch.setattr(ledger, "free_pool_spent", lambda since: state["pool_spent"])
    monkeypatch.setattr(ledger, "record_transaction", record_transaction)
    # "messages left": no run history, so the BILLING_USD_PER_MESSAGE estimate ($0.01)
    monkeypatch.setattr(ledger, "average_run_cost", lambda since, min_runs=50: None)
    monkeypatch.setattr(entitlements, "_per_message", None)
    # the offered prices follow the user's timezone (Indian ones for Asia/Kolkata)
    from harness.db.settings import Settings
    state["tz"] = "UTC"
    monkeypatch.setattr("harness.db.settings.get_settings", lambda uid: Settings(timezone=state["tz"]))
    return state


def _refusal(exc_info) -> str:
    assert exc_info.value.status_code == 402
    return exc_info.value.headers["X-Reason"]


# ------------------------------------------------------- entitlements

def test_free_user_cannot_pick_a_paid_model(billing):
    with pytest.raises(HTTPException) as e:
        entitlements.resolve_for_user("7", "gpt-5.5", None)
    assert _refusal(e) == "plan_required"
    assert e.value.detail["plan_needed"] == "pro"
    with pytest.raises(HTTPException) as e:
        entitlements.resolve_for_user("7", "gpt-5.4", None)
    assert e.value.detail["plan_needed"] == "plus"


def test_free_user_with_no_choice_gets_an_allowed_model_not_a_402(billing):
    spec, effort = entitlements.resolve_for_user("7", None, None)
    assert spec.tier == "basic"
    assert effort == "medium"


def test_effort_above_the_plan_ceiling_is_refused(billing):
    with pytest.raises(HTTPException) as e:
        entitlements.resolve_for_user("7", "gpt-5.6-luna", "high")
    assert _refusal(e) == "effort_not_allowed"


def test_research_mode_needs_a_paid_plan(billing):
    with pytest.raises(HTTPException) as e:
        entitlements.resolve_for_user("7", None, None, mode="research")
    assert _refusal(e) == "research_requires_plan"


def test_inherited_paid_model_falls_back_after_a_downgrade(billing):
    # a conversation started on Pro keeps working on Free, on a free model
    spec, effort = entitlements.resolve_for_user(
        "7", None, None, fallback_model="gpt-5.5", fallback_effort="xhigh")
    assert spec.tier == "basic" and effort == "medium"


def test_exhausted_allowance_without_credits_is_refused(billing):
    billing["usage"]["7"] = Decimal("0.50")
    with pytest.raises(HTTPException) as e:
        entitlements.resolve_for_user("7", None, None)
    assert _refusal(e) == "insufficient_balance"
    billing["credits"]["7"] = Decimal("2")            # credits carry the run
    assert entitlements.resolve_for_user("7", None, None)


def test_plus_unlocks_advanced_models_and_high_effort(billing):
    billing["accounts"]["7"] = Account(user_id="7", plan="plus")
    spec, effort = entitlements.resolve_for_user("7", "gpt-5.4", "high")
    assert (spec.id, effort) == ("gpt-5.4", "high")
    with pytest.raises(HTTPException) as e:
        entitlements.resolve_for_user("7", "gpt-6-astra", None)
    assert e.value.detail["plan_needed"] == "pro"


def test_billing_off_leaves_every_model_open(monkeypatch):
    monkeypatch.setenv("DODO_API_KEY", "")
    spec, _ = entitlements.resolve_for_user("7", "gpt-6-astra", "xhigh", mode="research")
    assert spec.id == "gpt-6-astra"


def test_full_free_pool_stops_free_users_without_credits(billing, monkeypatch):
    monkeypatch.setenv("BILLING_FREE_POOL_USD", "10")
    billing["pool_spent"] = Decimal("10")
    with pytest.raises(HTTPException) as e:
        entitlements.resolve_for_user("7", None, None)
    assert _refusal(e) == "free_pool_exhausted"
    assert e.value.detail["plan_needed"] == "plus"
    billing["credits"]["7"] = Decimal("1")            # bought credits still work
    assert entitlements.resolve_for_user("7", None, None)


def test_full_free_pool_does_not_touch_paying_users(billing, monkeypatch):
    monkeypatch.setenv("BILLING_FREE_POOL_USD", "10")
    billing["pool_spent"] = Decimal("50")
    billing["accounts"]["7"] = Account(user_id="7", plan="plus")
    spec, _ = entitlements.resolve_for_user("7", "gpt-5.4", None)
    assert spec.id == "gpt-5.4"


def test_no_pool_configured_means_no_cap(billing):
    billing["pool_spent"] = Decimal("1000")
    assert entitlements.resolve_for_user("7", None, None)


def test_free_spend_is_booked_to_the_pool_and_skips_it_once_full(billing, monkeypatch):
    calls = []
    monkeypatch.setattr(ledger, "settle_run", lambda uid, cost, **kw: calls.append(kw))
    entitlements.settle("7", Decimal("0.10"), "run-1")
    assert calls[-1]["allowance_kind"] == "free_cost" and calls[-1]["allowance"] == Decimal("0.25")

    monkeypatch.setenv("BILLING_FREE_POOL_USD", "10")
    billing["pool_spent"] = Decimal("10")
    entitlements.settle("7", Decimal("0.10"), "run-2")
    assert calls[-1]["allowance"] == Decimal("0")       # paid from credits only

    billing["accounts"]["7"] = Account(user_id="7", plan="plus")
    entitlements.settle("7", Decimal("0.10"), "run-3")
    assert calls[-1]["allowance_kind"] == "run_cost" and calls[-1]["allowance"] == Decimal("8.0")


def test_cost_comes_from_the_allowance_first_then_credits():
    assert ledger.split_cost(Decimal("0.30"), Decimal("0.50")) == (Decimal("0.30"), Decimal("0"))
    assert ledger.split_cost(Decimal("0.30"), Decimal("0.10")) == (Decimal("0.10"), Decimal("0.20"))
    assert ledger.split_cost(Decimal("0.30"), Decimal("-1")) == (Decimal("0"), Decimal("0.30"))


# ------------------------------------------------------- routes

def _app(*routers, user_id="7"):
    app = FastAPI()
    for r in routers:
        app.include_router(r)
    app.dependency_overrides[get_current_user] = lambda: {"user_id": user_id, "role": "user"}
    return TestClient(app)


def test_models_marks_paid_models_locked(billing):
    body = _app(models_route.router).get("/models").json()
    by_id = {m["id"]: m for m in body["models"]}
    assert body["plan"] == "free"
    assert by_id["gpt-5.5"]["locked"] and by_id["gpt-5.5"]["plan_needed"] == "pro"
    assert not by_id["gpt-5.6-luna"]["locked"]
    assert "high" not in by_id["gpt-5.6-luna"]["efforts"]
    assert body["default"]["model"] in {m for m, v in by_id.items() if not v["locked"]}


def test_stream_refuses_with_a_real_402_before_streaming(billing):
    r = _app(stream_route.router).post("/ask/stream", json={"question": "hi", "model": "gpt-5.5"})
    assert r.status_code == 402
    assert r.headers["X-Reason"] == "plan_required"


def test_approve_after_downgrade_is_refused_and_keeps_the_pending_action(billing, approve_app):  # noqa: F811
    app, store, executed, current, _ = approve_app
    current["user_id"] = "7"
    cp = pending_checkpoint("run-9", "7")
    cp.model = "gpt-5.5"
    store.save(cp)
    r = TestClient(app).post("/approve", json={"approval_id": "run-9", "decision": "approve"})
    assert r.status_code == 402
    assert executed == []
    assert store.rows["run-9"].pending_tool is not None     # can approve after upgrading


def _signed(payload: dict, secret: str = SECRET, webhook_id: str = "msg_1",
            ts: int | None = None) -> tuple[bytes, dict]:
    """Sign like Dodo (Standard Webhooks)."""
    raw = json.dumps(payload).encode()
    ts = int(time.time()) if ts is None else ts
    key = base64.b64decode(secret.removeprefix("whsec_"))
    sig = base64.b64encode(hmac.new(key, f"{webhook_id}.{ts}.".encode() + raw, hashlib.sha256).digest()).decode()
    return raw, {"webhook-id": webhook_id, "webhook-timestamp": str(ts),
                 "webhook-signature": f"v1,{sig}", "Content-Type": "application/json"}


def _subscription(event: str, status: str = "active", product: str = "pdt_plus", **extra) -> dict:
    return {
        "business_id": "bus_1", "type": event, "timestamp": "2026-10-01T00:00:00Z",
        "data": {"payload_type": "Subscription", "subscription_id": "sub_1", "product_id": product,
                 "status": status, "customer": {"customer_id": "cus_1", "email": "a@example.com"},
                 "metadata": {"user_id": "7"}, "next_billing_date": "2026-11-01T00:00:00Z",
                 "previous_billing_date": "2026-10-01T00:00:00Z",
                 "cancel_at_next_billing_date": False, "expires_at": None, **extra},
    }


def _post(c, payload, **kw):
    raw, headers = _signed(payload, **kw)
    return c.post("/billing/webhook", content=raw, headers=headers)


def test_webhook_rejects_a_bad_signature_and_a_stale_timestamp(billing):
    c = _app(billing_route.router)
    wrong = "whsec_" + base64.b64encode(b"wrong").decode()
    assert _post(c, _subscription("subscription.active"), secret=wrong).status_code == 401
    assert _post(c, _subscription("subscription.active"), ts=int(time.time()) - 3600).status_code == 401
    assert "7" not in billing["accounts"]


def test_subscription_active_upgrades_and_a_redelivery_is_a_noop(billing):
    c = _app(billing_route.router)
    assert _post(c, _subscription("subscription.active")).json()["result"] == "plan:plus"
    a = billing["accounts"]["7"]
    assert a.plan == "plus" and a.billing_subscription_id == "sub_1" and a.billing_customer_id == "cus_1"
    assert a.plan_period_start is not None
    assert _post(c, _subscription("subscription.active")).json()["result"] == "duplicate"


def test_cancelling_keeps_the_plan_until_expiry(billing):
    c = _app(billing_route.router)
    _post(c, _subscription("subscription.active", product="pdt_pro"), webhook_id="m1")
    _post(c, _subscription("subscription.updated", product="pdt_pro", cancel_at_next_billing_date=True), webhook_id="m2")
    a = billing["accounts"]["7"]
    assert (a.plan, a.plan_status) == ("pro", "cancelling") and a.plan_ends_at is not None
    _post(c, _subscription("subscription.expired", status="expired", product="pdt_pro"), webhook_id="m3")
    assert billing["accounts"]["7"].plan == "free"


def test_renewal_resets_the_allowance_period(billing):
    c = _app(billing_route.router)
    _post(c, _subscription("subscription.active"), webhook_id="m1")
    r = _post(c, _subscription("subscription.renewed"), webhook_id="m2")
    assert r.json()["result"] == "period_reset"
    assert billing["accounts"]["7"].plan_period_start.isoformat().startswith("2026-10-01")


def test_topup_payment_adds_credits_and_subscription_payments_do_not(billing):
    c = _app(billing_route.router)
    payment = {"type": "payment.succeeded", "data": {
        "payload_type": "Payment", "payment_id": "pay_1", "status": "succeeded", "subscription_id": None,
        "metadata": {"user_id": "7"}, "product_cart": [{"product_id": "pdt_topup", "quantity": 2}]}}
    assert _post(c, payment, webhook_id="m1").json()["result"] == "topup"
    assert billing["credits"]["7"] == Decimal("10.0")
    payment["data"]["subscription_id"] = "sub_1"
    assert _post(c, payment, webhook_id="m2").json()["result"] == "ignored:subscription_payment"
    assert billing["credits"]["7"] == Decimal("10.0")


def test_billing_summary_reports_allowance_and_credits(billing):
    billing["usage"]["7"] = Decimal("0.20")
    billing["credits"]["7"] = Decimal("1.5")
    body = _app(billing_route.router).get("/billing").json()
    assert body["plan"] == "free"
    assert body["allowance_left_usd"] == pytest.approx(0.05)      # $0.25 free allowance - $0.20 used
    assert body["credits_usd"] == 1.5
    assert (body["messages_left"], body["messages_total"]) == (5, 25)   # at $0.01 a message
    assert body["nudge"] is False          # 80% used, but bought credits cover what's next
    assert body["trial_days"] == 7 and body["trialing"] is False


def test_checkout_without_a_product_is_503(billing, monkeypatch):
    monkeypatch.setenv("DODO_PRODUCT_PLUS", "")
    r = _app(billing_route.router).post("/billing/checkout", json={"product": "plus"})
    assert r.status_code == 503            # no Dodo product configured for "plus"


def test_portal_needs_a_linked_customer(billing):
    assert _app(billing_route.router).post("/billing/portal").status_code == 404
