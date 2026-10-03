"""Auto model choice (providers/router.py): each message gets the model and
depth it needs, within the user's plan, with no extra model call."""
from decimal import Decimal

import pytest
from fastapi import HTTPException

from harness.billing import entitlements
from harness.billing.plans import PLANS
from harness.db import billing as billing_db
from harness.db import ledger
from harness.db.billing import Account
from harness.providers import router


@pytest.mark.parametrize("q,level", [
    ("remind me to call mom at 7", "quick"), ("weather tomorrow", "quick"), ("100 usd in inr", "quick"),
    ("add milk to my shopping list", "quick"), ("hi", "quick"),
    ("summarise my inbox", "everyday"), ("plan my day", "everyday"),
    ("draft a reply to Priya about the invoice", "write"), ("what's on my calendar tomorrow?", "everyday"),
    ("rewrite this so it sounds friendlier", "write"),
    ("compare the iPhone 17 and Pixel 11 for photography", "deep"),
    ("analyse my bank statement csv", "deep"), ("why does my python script fail", "deep"),
])
def test_levels(q, level):
    assert router.level_for(q) == level


def test_research_mode_and_long_requests_are_deep():
    assert router.level_for("tell me about routers", mode="research") == "deep"
    assert router.level_for(" ".join(["word"] * 90)) == "deep"


@pytest.mark.parametrize("plan,q,expected", [
    ("free", "compare A and B in depth", ("gpt-5.6-luna", "medium")),     # free: cheapest model, depth capped at medium
    ("plus", "compare A and B in depth", ("gpt-5.6-terra", "high")),
    ("pro", "compare A and B in depth", ("gpt-5.6-sol", "high")),
    ("pro", "remind me to stretch", ("gpt-5.6-luna", "low")),            # quick stays cheap, even on Pro
    ("plus", "summarise my inbox", ("gpt-5.6-luna", "medium")),           # reading mail: the cheap model
    ("plus", "draft a reply to Priya about the invoice", ("gpt-5.6-terra", "medium")),  # writing: the mid model
    ("free", "draft a reply to Priya about the invoice", ("gpt-5.6-luna", "medium")),
])
def test_choice_respects_the_plan(plan, q, expected):
    p = PLANS[plan]
    c = router.choose(q, allowed=p.allows_model, max_effort=p.max_effort)
    assert (c.model, c.effort) == expected


@pytest.fixture
def billing_on(monkeypatch):
    monkeypatch.setenv("DODO_API_KEY", "dodo_test")
    monkeypatch.setattr(ledger, "period_usage", lambda uid, since: Decimal(0))
    monkeypatch.setattr(ledger, "credit_balance", lambda uid: Decimal(0))
    monkeypatch.setattr(ledger, "free_pool_spent", lambda since: Decimal(0))

    def acct(plan):
        monkeypatch.setattr(billing_db, "get_account", lambda uid: Account(user_id=uid, plan=plan))
    return acct


def test_auto_never_asks_a_free_user_to_upgrade_for_the_model(billing_on):
    billing_on("free")
    spec, effort = entitlements.resolve_for_user("7", "auto", None, question="analyse this spreadsheet")
    assert spec.id == "gpt-5.6-luna" and effort == "medium"


def test_auto_follows_the_conversation(billing_on):
    billing_on("pro")
    spec, _ = entitlements.resolve_for_user("7", None, None, fallback_model="auto", question="weather in Pune")
    assert spec.id == "gpt-5.6-luna"
    spec, _ = entitlements.resolve_for_user("7", None, None, fallback_model="auto", question="write a business plan")
    assert spec.id == "gpt-5.6-sol"


def test_auto_research_on_free_still_needs_plus(billing_on):
    billing_on("free")
    with pytest.raises(HTTPException) as e:
        entitlements.resolve_for_user("7", "auto", None, mode="research", question="history of tea")
    assert e.value.headers["X-Reason"] == "research_requires_plan"


def test_auto_without_billing_and_a_hand_picked_model_wins(monkeypatch):
    monkeypatch.setenv("DODO_API_KEY", "")
    spec, effort = entitlements.resolve_for_user("7", "auto", None, question="explain why the sky is blue in depth")
    assert (spec.id, effort) == ("gpt-5.6-sol", "high")
    spec, _ = entitlements.resolve_for_user("7", "gpt-4.1-mini", None, question="explain why the sky is blue in depth")
    assert spec.id == "gpt-4.1-mini"
