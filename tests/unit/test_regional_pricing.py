# ruff: noqa: F811  -- pytest injects the imported `billing` fixture by parameter name
"""Indian pricing and yearly plans: which prices are offered, which Dodo product
is sold, what the webhook records, and the monthly allowance inside a yearly plan."""
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from harness.api.routes import billing as billing_route
from harness.billing import entitlements
from harness.billing.plans import parse_product_key, product_key, region_for_timezone
from harness.db.billing import Account
from tests.unit.test_billing import _app, _post, _subscription, billing  # noqa: F401

ALL = {"DODO_PRODUCT_PLUS_ANNUAL": "pdt_plus_y", "DODO_PRODUCT_PRO_ANNUAL": "pdt_pro_y",
       "DODO_PRODUCT_PLUS_IN": "pdt_plus_in", "DODO_PRODUCT_PRO_IN": "pdt_pro_in",
       "DODO_PRODUCT_PLUS_IN_ANNUAL": "pdt_plus_in_y", "DODO_PRODUCT_PRO_IN_ANNUAL": "pdt_pro_in_y"}


def _products(monkeypatch, **only):
    for k, v in (only or ALL).items():
        monkeypatch.setenv(k, v)


def test_product_keys_and_regions():
    assert region_for_timezone("Asia/Kolkata") == region_for_timezone("Asia/Calcutta") == "in"
    assert region_for_timezone("Europe/London") == region_for_timezone(None) == "intl"
    for plan in ("plus", "pro"):
        for region in ("intl", "in"):
            for interval in ("month", "year"):
                assert parse_product_key(product_key(plan, region, interval)) == (plan, region, interval)
    assert product_key("pro", "in", "year") == "pro_in_annual"


def test_india_sees_rupee_prices_and_smaller_allowances(billing, monkeypatch):
    _products(monkeypatch)
    billing["tz"] = "Asia/Kolkata"
    body = _app(billing_route.router).get("/billing").json()
    assert body["region"] == "in"
    plus = next(p for p in body["plans"] if p["id"] == "plus")
    assert plus["prices"]["month"]["label"] == "₹499" and plus["prices"]["year"]["label"] == "₹4,999"
    assert plus["monthly_allowance_usd"] == 2.0
    billing["tz"] = "America/New_York"
    body = _app(billing_route.router).get("/billing").json()
    plus = next(p for p in body["plans"] if p["id"] == "plus")
    assert body["region"] == "intl" and plus["prices"]["month"]["label"] == "$20" and plus["monthly_allowance_usd"] == 8.0


def test_no_indian_product_means_international_prices_and_no_yearly_without_its_product(billing):
    billing["tz"] = "Asia/Kolkata"
    body = _app(billing_route.router).get("/billing").json()
    plus = next(p for p in body["plans"] if p["id"] == "plus")
    assert body["region"] == "intl" and plus["prices"] == {"month": {"amount": 20, "currency": "USD", "label": "$20"}}


@pytest.mark.parametrize("configured,interval,tz,sold", [
    (ALL, "year", "Asia/Kolkata", "plus_in_annual"),
    ({"DODO_PRODUCT_PLUS_IN": "pdt_plus_in"}, "year", "Asia/Kolkata", "plus_in"),        # no Indian yearly: monthly
    ({"DODO_PRODUCT_PLUS_ANNUAL": "pdt_plus_y"}, "year", "Asia/Kolkata", "plus_annual"),  # no Indian product at all
    (ALL, "month", "Europe/Berlin", "plus"),
    (ALL, "year", "Europe/Berlin", "plus_annual"),
])
def test_checkout_sells_the_closest_configured_product(billing, monkeypatch, configured, interval, tz, sold):
    _products(monkeypatch, **configured)
    billing["tz"] = tz
    seen = []

    async def fake_checkout(product, user_id, email, *, trial_days=0):
        seen.append(product)
        return "https://checkout.example/1"
    monkeypatch.setattr(billing_route.dodo, "create_checkout", fake_checkout)
    r = _app(billing_route.router).post("/billing/checkout", json={"product": "plus", "interval": interval})
    assert r.json()["product"] == sold and seen == [sold]


def test_webhook_records_an_indian_yearly_plan(billing, monkeypatch):
    _products(monkeypatch)
    c = _app(billing_route.router)
    assert _post(c, _subscription("subscription.active", product="pdt_plus_in_y"), webhook_id="w1").json()["result"] == "plan:plus"
    a = billing["accounts"]["7"]
    assert (a.plan, a.plan_region, a.plan_interval) == ("plus", "in", "year")
    assert entitlements.standing("7").allowance == Decimal("2.0")


def test_switching_monthly_to_yearly_starts_a_fresh_period(billing, monkeypatch):
    _products(monkeypatch)
    old = datetime(2026, 9, 10, tzinfo=UTC)
    billing["accounts"]["7"] = Account(user_id="7", plan="plus", plan_status="active", plan_period_start=old,
                                       billing_subscription_id="sub_1")
    _post(_app(billing_route.router), _subscription("subscription.plan_changed", product="pdt_plus_y"), webhook_id="w2")
    a = billing["accounts"]["7"]
    assert a.plan_interval == "year" and a.plan_period_start > old


@pytest.mark.parametrize("now,expected", [
    ("2026-03-15", "2026-02-28"),          # 31 Jan start: February's anniversary is the 28th
    ("2026-03-31", "2026-03-31"),
    ("2026-01-31", "2026-01-31"),          # the start itself
    ("2027-01-05", "2026-12-31"),
])
def test_a_yearly_plan_resets_its_allowance_monthly(now, expected):
    a = Account(user_id="7", plan="plus", plan_interval="year", plan_period_start=datetime(2026, 1, 31, 9, tzinfo=UTC))
    got = entitlements.period_start(a, now=datetime.fromisoformat(now).replace(hour=12, tzinfo=UTC))
    assert got.date().isoformat() == expected
    monthly = Account(user_id="7", plan="plus", plan_interval="month", plan_period_start=datetime(2026, 1, 31, 9, tzinfo=UTC))
    assert entitlements.period_start(monthly, now=datetime(2026, 3, 15, tzinfo=UTC)).date().isoformat() == "2026-01-31"


def test_the_public_homepage_prices_follow_the_visitors_timezone(billing, monkeypatch):
    # signed out: no account, no JWT -- only the device timezone decides
    _products(monkeypatch)
    client = _app(billing_route.router)
    india = client.get("/billing/prices", params={"tz": "Asia/Calcutta"}).json()      # Chrome's legacy name too
    plus = next(p for p in india["plans"] if p["id"] == "plus")
    assert india["region"] == "in" and plus["prices"]["month"]["label"] == "₹499"
    world = client.get("/billing/prices", params={"tz": "Europe/Berlin"}).json()
    pro = next(p for p in world["plans"] if p["id"] == "pro")
    assert world["region"] == "intl" and pro["prices"]["month"]["label"] == "$100"
    assert client.get("/billing/prices").json()["region"] == "intl"                     # no timezone sent
    assert india["trial_days"] >= 0


def test_the_homepage_never_offers_rupees_checkout_would_not_charge(billing):
    # no Indian product configured: Indian visitors see (and would pay) dollars
    body = _app(billing_route.router).get("/billing/prices", params={"tz": "Asia/Kolkata"}).json()
    plus = next(p for p in body["plans"] if p["id"] == "plus")
    assert body["region"] == "intl" and plus["prices"]["month"]["label"] == "$20"
