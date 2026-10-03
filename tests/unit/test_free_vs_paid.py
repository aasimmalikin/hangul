# ruff: noqa: F811  -- pytest injects the imported `billing` fixture by parameter name
"""Free vs paid: Google write actions are Plus, the daily brief is Plus (weekly
on Free), the Plus trial, "messages left" and the 80% upgrade nudge."""
import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi import HTTPException

from harness.api.routes import billing as billing_route
from harness.api.routes import settings as settings_route
from harness.billing import entitlements
from harness.db import tasks as tasks_db
from harness.db.billing import Account
from harness.policy.audit import AuditLog
from harness.policy.guarded import guarded_dispatch
from harness.policy.policy import ToolPolicy
from harness.policy.tiers import Tier
from harness.tools.base import Tool
from tests.unit.test_billing import _app, _post, _subscription, billing  # noqa: F401


def _tool(name):
    async def run(**_kw):
        return f"{name} ran"
    return Tool(name=name, description="", parameter={"type": "object", "properties": {}}, handler=run)


GOOGLE = ["gmail__search_messages", "gmail__get_thread", "gmail__send_message", "gmail__send_draft",
          "gmail__create_draft", "calendar__list_events", "calendar__create_event", "calendar__delete_event",
          "sheets__read_range", "sheets__append_rows", "docs__append_text"]


def test_free_reads_google_but_acting_on_it_is_plus(billing):
    gated = {t.name for t in entitlements.gate_tools("7", [_tool(n) for n in GOOGLE]) if t.upgrade_stub}
    assert gated == {"gmail__send_message", "gmail__send_draft", "gmail__create_draft", "calendar__create_event",
                     "calendar__delete_event", "sheets__append_rows", "docs__append_text"}
    billing["accounts"]["7"] = Account(user_id="7", plan="plus")
    assert not any(t.upgrade_stub for t in entitlements.gate_tools("7", [_tool(n) for n in GOOGLE]))


def test_an_upgrade_stub_never_waits_for_approval(billing):
    stub = next(t for t in entitlements.gate_tools("7", [_tool("gmail__send_message")]))
    policy = ToolPolicy(tiers={"gmail__send_message": Tier.DESTRUCTIVE})
    result = asyncio.run(guarded_dispatch(stub, {}, policy, AuditLog("/dev/null")))
    assert "Plus plan" in result.content          # the upgrade card's text, not "requires human approval"
    real = asyncio.run(guarded_dispatch(_tool("gmail__send_message"), {}, policy, AuditLog("/dev/null")))
    assert "requires human approval" in real.content


# ------------------------------------------------------------------ scheduled tasks

def _task(**kw):
    return settings_route.TaskIn(title="Morning brief", question="brief", **kw)


def test_free_cannot_schedule_daily_but_the_one_tap_brief_becomes_weekly(billing):
    with pytest.raises(HTTPException) as e:
        settings_route._fit_schedule("7", _task(daily_at="08:00"))
    assert e.value.status_code == 402 and e.value.detail["plan_needed"] == "plus"
    assert settings_route._fit_schedule("7", _task(daily_at="08:00", fit_plan=True)) == (tasks_db.WEEK_MINUTES, "08:00")
    assert settings_route._fit_schedule("7", _task(every_minutes=tasks_db.WEEK_MINUTES)) == (tasks_db.WEEK_MINUTES, None)
    billing["accounts"]["7"] = Account(user_id="7", plan="plus")
    assert settings_route._fit_schedule("7", _task(daily_at="08:00")) == (None, "08:00")


def test_weekly_runs_at_the_next_hh_mm_then_every_seven_days():
    now = datetime(2026, 10, 5, 6, 0, tzinfo=UTC)             # a Monday, 06:00 UTC
    first = tasks_db.compute_next_run(tasks_db.WEEK_MINUTES, "08:00", "UTC", after=now)
    assert first == datetime(2026, 10, 5, 8, 0, tzinfo=UTC)
    after_run = tasks_db.compute_next_run(tasks_db.WEEK_MINUTES, "08:00", "UTC", after=first, ran=True)
    assert after_run == first + timedelta(days=7)
    # a daily task still runs daily
    assert tasks_db.compute_next_run(None, "08:00", "UTC", after=first, ran=True) == first + timedelta(days=1)
    assert tasks_db.interval_minutes(tasks_db.WEEK_MINUTES, "08:00") == tasks_db.WEEK_MINUTES
    assert tasks_db.interval_minutes(None, "08:00") == 24 * 60


# ------------------------------------------------------------------ the Plus trial

def test_checkout_offers_the_trial_once(billing, monkeypatch):
    seen = []

    async def fake_checkout(product, user_id, email, *, trial_days=0):
        seen.append((product, trial_days))
        return "https://checkout.example/1"

    monkeypatch.setattr(billing_route.dodo, "create_checkout", fake_checkout)
    c = _app(billing_route.router)
    assert c.post("/billing/checkout", json={"product": "plus"}).json() == {"url": "https://checkout.example/1", "trial_days": 7}
    assert c.post("/billing/checkout", json={"product": "pro"}).json()["trial_days"] == 0
    billing["accounts"]["7"] = Account(user_id="7", plan="free", billing_subscription_id="sub_old")
    assert c.post("/billing/checkout", json={"product": "plus"}).json()["trial_days"] == 0   # had a plan before
    assert seen == [("plus", 7), ("pro", 0), ("plus", 0)]


def test_trial_has_its_own_allowance_until_the_first_charge(billing):
    c = _app(billing_route.router)
    trial = _subscription("subscription.active", metadata={"user_id": "7", "trial": "1"})
    assert _post(c, trial, webhook_id="t1").json()["result"] == "plan:plus"
    a = billing["accounts"]["7"]
    assert (a.plan, a.plan_status) == ("plus", "trialing")
    body = c.get("/billing").json()
    assert body["trialing"] is True and body["allowance_usd"] == 2.0 and body["trial_days"] == 0
    assert entitlements.standing("7").allowance == Decimal("2.0")
    # an update during the trial keeps it a trial
    _post(c, _subscription("subscription.updated", metadata={"user_id": "7", "trial": "1"}), webhook_id="t2")
    assert billing["accounts"]["7"].plan_status == "trialing"
    # the first real charge: a paid period with the full Plus allowance
    _post(c, _subscription("subscription.renewed", metadata={"user_id": "7", "trial": "1"}), webhook_id="t3")
    a = billing["accounts"]["7"]
    assert (a.plan, a.plan_status) == ("plus", "active")
    assert entitlements.standing("7").allowance == Decimal("8.0")


def test_a_trial_that_is_not_paid_drops_to_free(billing):
    c = _app(billing_route.router)
    _post(c, _subscription("subscription.active", metadata={"user_id": "7", "trial": "1"}), webhook_id="t1")
    _post(c, _subscription("subscription.on_hold", status="on_hold", metadata={"user_id": "7", "trial": "1"}),
          webhook_id="t2")
    assert billing["accounts"]["7"].plan == "free"


# ------------------------------------------------------------------ messages left and the nudge

def test_messages_left_and_the_nudge_at_80_percent(billing):
    billing["usage"]["7"] = Decimal("0.21")            # 84% of the $0.25 free allowance, no credits
    body = _app(billing_route.router).get("/billing").json()
    assert body["messages_left"] == 4 and body["messages_total"] == 25
    assert body["nudge"] is True
    billing["usage"]["7"] = Decimal("0.10")
    assert _app(billing_route.router).get("/billing").json()["nudge"] is False
