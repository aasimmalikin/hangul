"""The "Before you go" cancel flow (/billing/leave, /billing/resume): every
choice is recorded with its reason, cancelling is one call that keeps the plan
until the period ends, Pro can switch down to Plus, and cancelling can be undone."""
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from harness.api.auth import get_current_user
from harness.api.routes import billing as billing_route
from harness.billing import dodo
from harness.db import billing as billing_db
from harness.db.billing import Account

RENEWS = datetime(2026, 11, 3, tzinfo=UTC)


@pytest.fixture
def env(monkeypatch):
    st = {"acct": Account(user_id="7", plan="pro", plan_status="active", plan_renews_at=RENEWS,
                          billing_subscription_id="sub_1"), "churn": [], "dodo": []}

    def update(uid, **f):
        for k, v in f.items():
            setattr(st["acct"], k, v)
        return True
    monkeypatch.setattr(billing_db, "get_account", lambda uid: st["acct"])
    monkeypatch.setattr(billing_db, "update_account", update)
    monkeypatch.setattr(billing_db, "record_churn", lambda uid, **kw: st["churn"].append(kw))

    async def cancel(sub, flag, comment=""):
        st["dodo"].append(("cancel", sub, flag, comment))
        return {}

    async def change(sub, product):
        st["dodo"].append(("change", sub, product))
        return {}
    monkeypatch.setattr(dodo, "set_cancel_at_period_end", cancel)
    monkeypatch.setattr(dodo, "change_plan", change)
    app = FastAPI()
    app.include_router(billing_route.router)
    app.dependency_overrides[get_current_user] = lambda: {"user_id": "7"}
    st["client"] = TestClient(app)
    return st


def test_keeping_the_plan_records_why_they_almost_left(env):
    r = env["client"].post("/billing/leave", json={"reason": "not_using", "action": "keep"})
    assert r.json()["outcome"] == "kept" and env["dodo"] == []
    assert env["churn"] == [{"plan": "pro", "reason": "not_using", "detail": "", "outcome": "kept"}]


def test_pro_can_switch_down_to_plus_instead_of_leaving(env):
    r = env["client"].post("/billing/leave", json={"reason": "too_expensive", "action": "downgrade"})
    assert r.json() == {"outcome": "downgraded", "plan": "plus"}
    assert env["dodo"] == [("change", "sub_1", "plus")] and env["acct"].plan == "plus"


def test_cancel_is_one_call_and_the_plan_runs_to_the_period_end(env):
    r = env["client"].post("/billing/leave", json={"reason": "missing_feature", "detail": "WhatsApp", "action": "cancel"})
    assert r.json() == {"outcome": "cancelled", "plan": "pro", "ends_at": RENEWS.isoformat()}
    assert env["dodo"] == [("cancel", "sub_1", True, "missing_feature: WhatsApp")]
    assert (env["acct"].plan, env["acct"].plan_status, env["acct"].plan_ends_at) == ("pro", "cancelling", RENEWS)
    assert env["churn"][0]["detail"] == "WhatsApp"


def test_cancelling_can_be_undone(env):
    env["client"].post("/billing/leave", json={"reason": "other", "action": "cancel"})
    r = env["client"].post("/billing/resume")
    assert r.json() == {"plan": "pro", "status": "active"}
    assert env["dodo"][-1] == ("cancel", "sub_1", False, "")
    assert env["acct"].plan_renews_at == RENEWS and env["acct"].plan_ends_at is None


def test_rules(env):
    env["acct"].plan = "plus"
    assert env["client"].post("/billing/leave", json={"reason": "too_expensive", "action": "downgrade"}).status_code == 409
    env["acct"].plan = "free"
    assert env["client"].post("/billing/leave", json={"reason": "other", "action": "cancel"}).status_code == 409
    assert env["client"].post("/billing/leave", json={"reason": "bogus", "action": "cancel"}).status_code == 422
