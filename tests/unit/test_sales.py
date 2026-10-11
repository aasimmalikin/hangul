"""How's business (harness.sales): the forecast and its honesty rules, importing
billing-app exports, the margin-checked playbook, the Free / Plus / Pro split,
per-user isolation, the chat tool and the evening alert."""
import asyncio
import io
import random
from datetime import date, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from harness.api.auth import get_current_user
from harness.api.routes import business as routes
from harness.billing import entitlements
from harness.db import billing as billing_db
from harness.db import brands as brands_db
from harness.db import launch as launch_db
from harness.db import sales as db
from harness.db.models import Brand, Business, BusinessDay, BusinessEvent, LaunchPlan, User
from harness.sales import forecast as fc
from harness.sales import imports, playbook, service


@compiles(JSONB, "sqlite")
def _jsonb_as_json(_type, _compiler, **_kw):
    return "JSON"


TODAY = date(2026, 9, 15)            # a Tuesday: tomorrow is Wednesday
WD = [0.9, 0.85, 0.9, 0.95, 1.1, 1.35, 1.25]


def rain_on(d: date) -> float:
    """The same 'weather' for a date everywhere in these tests (sales and the fake weather service)."""
    return 18.0 if d == TODAY + timedelta(days=1) else random.Random(d.toordinal()).choice([0, 0, 0, 0, 0, 9, 18])


def synthetic(n: int, *, seed: int = 1, rain_effect: float = 0.7, end: date = TODAY) -> list[fc.Day]:
    rnd = random.Random(seed)
    start = end - timedelta(days=n - 1)
    out = []
    for i in range(n):
        d = start + timedelta(days=i)
        rain = rain_on(d)
        s = 15000 * WD[d.weekday()] * (rain_effect if rain > 5 else 1) * rnd.gauss(1, 0.05)
        out.append(fc.Day(d, round(s), rain=rain, tmax=24 + rnd.gauss(0, 2)))
    return out


# ------------------------------------------------------------ the forecast

def test_no_forecast_until_two_weeks():
    f = fc.forecast(synthetic(10), fc.Target(TODAY + timedelta(days=1)))
    assert f.status == "learning" and f.days_needed == 4 and f.value is None


def test_a_closed_day_is_zero():
    f = fc.forecast(synthetic(30), fc.Target(TODAY + timedelta(days=1), closed=True))
    assert f.status == "closed" and f.value == 0


def test_with_enough_history_the_regression_wins_and_explains_rain_and_weekday():
    hist = synthetic(100)
    f = fc.forecast(hist, fc.Target(TODAY + timedelta(days=1), rain=15, tmax=24))
    assert f.status == "ready" and f.model == "regression" and f.beats_baseline
    truth = 15000 * WD[2] * 0.7
    assert abs(f.value - truth) / truth < 0.15
    assert f.low <= f.value <= f.high
    keys = [r["key"] for r in f.reasons]
    assert "rain" in keys and "weekday" in keys
    assert next(r for r in f.reasons if r["key"] == "rain")["effect"] < 0
    assert f.accuracy is not None and f.accuracy < 0.15 and f.backtest_days == fc.BACKTEST


def test_every_model_is_judged_on_the_same_days_and_the_best_is_chosen():
    hist = synthetic(70)
    bt = fc.backtest(hist, ["naive", "weekday", "regression"])
    assert len({len(p) for p in bt.values()}) == 1                       # same days for all
    f = fc.forecast(hist, fc.Target(TODAY + timedelta(days=1)))
    maes = {m: fc._mae(p) for m, p in bt.items()}
    assert f.model == min(maes, key=maes.get)
    assert f.beats_baseline == (f.model != "naive" and maes[f.model] < maes["naive"])


def test_a_festival_never_seen_is_flagged():
    hist = synthetic(40, end=date(2026, 12, 24))                         # tomorrow is Christmas
    f = fc.forecast(hist, fc.Target(date(2026, 12, 25)))
    assert any("Christmas" in n for n in f.notes)


# ------------------------------------------------------------ imports

def _xlsx(rows) -> bytes:
    from openpyxl import Workbook
    wb = Workbook()
    for r in rows:
        wb.active.append(r)
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


def test_a_vyapar_style_report_keeps_only_sales():
    data = _xlsx([["Chinar Café"], ["Sale Report"], [],
                  ["Date", "Invoice No", "Transaction Type", "Total Amount", "Payment Status"],
                  ["01/09/2026", "1", "Sale", "₹1,250.00", "Paid"], ["01/09/2026", "2", "Sale", "₹750", "Unpaid"],
                  ["01/09/2026", "3", "Sale Return", "₹100", "Paid"], ["02/09/2026", "4", "Sale", "₹2,000", "Cancelled"],
                  ["02/09/2026", "5", "Sale", "₹900", "Paid"], ["03/09/2026", "P1", "Purchase", "₹500", "Paid"],
                  ["", "", "Total", "₹4,900", ""]])
    r = imports.parse(data, "sales.xlsx")
    assert (r.date_col, r.amount_col) == ("Date", "Total Amount")
    assert r.days == [{"day": "2026-09-01", "sales": 2000.0, "bills": 2}, {"day": "2026-09-02", "sales": 900.0, "bills": 1}]
    assert any("cancelled" in n for n in r.notes)


def test_a_upi_statement_keeps_credits_and_reads_iso_dates():
    csv = ("Transaction Date,Transaction ID,Type,Amount,Status\n2026-09-01 10:01,T1,CREDIT,120,SUCCESS\n"
           "2026-09-01 12:00,T2,CREDIT,80,FAILED\n2026-09-02 09:00,T3,DEBIT,500,SUCCESS\n2026-09-02 09:30,T4,CREDIT,60,SUCCESS\n")
    r = imports.parse(csv.encode(), "phonepe.csv")
    assert [(d["day"], d["sales"]) for d in r.days] == [("2026-09-01", 120.0), ("2026-09-02", 60.0)]


def test_a_daily_summary_uses_its_own_bill_count():
    r = imports.parse(b'Date,Orders,Net Sales\n13/09/2026,40,"12,400"\n14/09/2026,35,"10,050"\n', "petpooja.csv")
    assert r.days == [{"day": "2026-09-13", "sales": 12400.0, "bills": 40}, {"day": "2026-09-14", "sales": 10050.0, "bills": 35}]


def test_an_unknown_layout_names_the_columns_and_can_be_mapped():
    raw = b"When,Ref,Rupees\n13/09/2026,a,100\n14/09/2026,b,200\n"
    with pytest.raises(imports.ImportProblem) as e:
        imports.parse(raw, "x.csv")
    assert "Rupees" in str(e.value)
    r = imports.parse(raw, "x.csv", date_col="When", amount_col="Rupees")
    assert sum(d["sales"] for d in r.days) == 300
    with pytest.raises(imports.ImportProblem):
        imports.parse(b"hello", "notes.txt")


# ------------------------------------------------------------ the playbook

def test_discounts_never_eat_the_margin():
    assert playbook.safe_discount(15, 0.38) == 15
    assert playbook.safe_discount(20, 0.78) == 10            # 1 - 0.78 - 0.10 = 12% -> 10
    assert playbook.safe_discount(15, 0.88) == 0
    ideas = playbook.suggest("retail_shop", ["after_festival"], TODAY, price=600, plan_assumptions=None)
    clearance = next(i for i in ideas if i["key"] == "clearance")
    assert clearance["discount"] == 10 and clearance["discount_cut"] and clearance["left_per_sale"] > 0
    thin = playbook.suggest("cafe", ["weekday"], TODAY, price=300,
                            plan_assumptions={"variable": [{"pct": 0.88}]})
    assert all(i["discount"] == 0 for i in thin) and "margin is too thin" in thin[0]["idea"]


def test_ideas_follow_the_causes_and_name_the_day():
    ideas = playbook.suggest("cafe", ["rain", "weekday"], TODAY + timedelta(days=1), price=320, plan_assumptions=None)
    assert ideas[0]["cause"] == "rain" and ideas[0]["layout"] in ("offer", "showcase")
    assert any("Wednesday" in i["headline"] for i in ideas)


def test_slow_means_below_break_even_or_well_below_usual():
    assert playbook.is_slow({"status": "ready", "value": 9000, "typical": 10000}, 9500) == (True, "below_breakeven")
    assert playbook.is_slow({"status": "ready", "value": 8000, "typical": 10000}, None) == (True, "below_usual")
    assert playbook.is_slow({"status": "ready", "value": 9000, "typical": 10000}, None) == (False, "")
    assert playbook.is_slow({"status": "learning"}, 100) == (False, "")


# ------------------------------------------------------------ store, routes, plans

@pytest.fixture
def store(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    for m in (Business, BusinessDay, BusinessEvent, User, Brand, LaunchPlan):
        m.__table__.create(engine)
    maker = sessionmaker(engine)
    for mod in (db, billing_db, brands_db, launch_db):
        monkeypatch.setattr(mod, "SessionLocal", maker)
    with maker() as s:
        s.add_all([User(id=7, plan="pro"), User(id=8, plan="free"), User(id=9, plan="plus")])
        s.commit()
    monkeypatch.setattr(entitlements, "billing_enabled", lambda: True)
    monkeypatch.setattr(service, "local_today", lambda uid: TODAY)
    weather_calls = []

    async def fake_geo(city):
        return (34.08, 74.8)

    async def fake_days(lat, lon, start, end, today):
        weather_calls.append((start, end))
        out, d = {}, start
        while d <= end:
            out[d] = (rain_on(d), 24.0)
            d += timedelta(days=1)
        return out

    monkeypatch.setattr(service.weather, "geocode", fake_geo)
    monkeypatch.setattr(service.weather, "days", fake_days)
    return maker


def client(user="7"):
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[get_current_user] = lambda: {"user_id": user}
    return TestClient(app)


def seed(business_id: int, n: int = 100):
    hist = synthetic(n)
    db.import_days(business_id, [{"day": d.day.isoformat(), "sales": d.sales, "bills": round(d.sales / 320)} for d in hist])


def make(user="7", **kw) -> int:
    r = client(user).post("/business", json={"name": "Chinar Café", "kind": "cafe", "city": "Srinagar", **kw})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_business_limits_follow_the_plan(store):
    make("8")
    r = client("8").post("/business", json={"name": "Second", "kind": "cafe"})
    assert r.status_code == 402 and r.json()["detail"]["code"] == "business_limit"
    for i in range(5):
        make("7", name=f"Outlet {i}")
    assert client("7").post("/business", json={"name": "Sixth"}).status_code == 402
    assert client("7").post("/business", json={"name": "X", "kind": "spaceship"}).status_code == 422


def test_free_logs_and_sees_the_week_but_no_forecast(store):
    bid = make("8")
    seed(bid, 30)
    r = client("8").post(f"/business/{bid}/days", json={"sales": 16400, "bills": 52})
    assert r.status_code == 200 and r.json()["day"] == TODAY.isoformat() and r.json()["sales"] == 16400
    ov = client("8").get(f"/business/{bid}/overview").json()
    assert ov["week"]["total"] > 0 and ov["logged_today"]
    assert ov["forecast"] == {"status": "ready", "days_logged": 30, "days_needed": 0}
    assert ov["locked"] == [{"feature": "Tomorrow's sales forecast", "plan": "plus"}] and ov["ideas"] == []


def test_plus_sees_the_forecast_and_one_idea_a_week_but_not_why(store):
    bid = make("9")
    seed(bid)
    ov = client("9").get(f"/business/{bid}/overview").json()
    f = ov["forecast"]
    assert f["status"] == "ready" and f["value"] and f["low"] <= f["value"] <= f["high"] and f["reasons"] == []
    assert ov["slow"]["slow"]                                   # rainy Wednesday
    assert len(ov["ideas"]) == 1 and ov["ideas_left"] == 1
    assert {"feature": "Why tomorrow looks this way", "plan": "pro"} in ov["locked"]
    key = ov["ideas"][0]["key"]
    used = client("9").post(f"/business/{bid}/ideas/{key}/use").json()
    assert used["studio_url"] == "/brands"                     # no brand linked yet
    again = client("9").get(f"/business/{bid}/overview").json()
    assert again["ideas_left"] == 0 and len(again["ideas"]) == 1     # tomorrow's idea stays open
    # next week the allowance is back
    service.local_today = lambda uid: TODAY + timedelta(days=7)
    try:
        assert service.ideas_left(bid, TODAY + timedelta(days=7)) == 1
    finally:
        service.local_today = lambda uid: TODAY


def test_pro_sees_why_and_every_idea_with_a_ready_post(store):
    with store() as s:
        s.add(Brand(id=40, user_id=7, name="Chinar Café", colors=[], hashtags=[]))
        s.commit()
    bid = make("7", brand_id=40)
    seed(bid)
    ov = client("7").get(f"/business/{bid}/overview").json()
    assert ov["forecast"]["reasons"] and ov["locked"] == []
    assert any(r["key"] == "rain" for r in ov["forecast"]["reasons"])
    assert len(ov["ideas"]) >= 2 and ov["ideas"][0]["cause"] == "rain"
    assert ov["expected"] and len(ov["expected"]) <= service.CHART_DAYS
    used = client("7").post(f"/business/{bid}/ideas/{ov['ideas'][0]['key']}/use").json()
    assert used["studio_url"].startswith("/brands/40?tab=create&layout=")
    assert "from=business" in used["studio_url"]


def test_weather_is_fetched_once_and_kept(store):
    bid = make("7")
    seed(bid, 30)
    client("7").get(f"/business/{bid}/overview")
    with store() as s:
        assert all(d.rain_mm is not None for d in s.query(BusinessDay).filter_by(business_id=bid))


def test_a_linked_launch_plan_sets_break_even(store):
    from harness.launch import plan as planner
    p = launch_db.create("7", planner.new_plan(kind="cafe", city="Srinagar", size="small"))
    bid = make("7", launch_plan_id=p["id"])
    seed(bid)
    ov = client("7").get(f"/business/{bid}/overview").json()
    assert ov["plan"]["breakeven"] > 0 and ov["slow"]["breakeven"] == ov["plan"]["breakeven"]
    assert client("9").post("/business", json={"name": "X", "launch_plan_id": p["id"]}).status_code == 422   # not theirs


def test_days_rules_and_isolation(store):
    bid = make("7")
    c = client("7")
    assert c.post(f"/business/{bid}/days", json={"day": (TODAY + timedelta(days=2)).isoformat(), "sales": 1}).status_code == 422
    assert c.post(f"/business/{bid}/days", json={"day": (TODAY + timedelta(days=1)).isoformat(), "sales": 5}).status_code == 422
    assert c.post(f"/business/{bid}/days", json={"day": (TODAY + timedelta(days=1)).isoformat(), "closed": True}).status_code == 200
    c.post(f"/business/{bid}/days", json={"sales": 1000, "bills": 3})
    r = c.post(f"/business/{bid}/days", json={"sales": 500, "bills": 2, "add": True}).json()
    assert (r["sales"], r["bills"]) == (1500, 5)
    for method, path in (("get", f"/business/{bid}/overview"), ("post", f"/business/{bid}/days"),
                         ("delete", f"/business/{bid}"), ("patch", f"/business/{bid}")):
        kw = {"json": {"sales": 1}} if method == "post" else {"json": {"name": "x"}} if method == "patch" else {}
        assert getattr(client("9"), method)(path, **kw).status_code == 404, path


def test_import_previews_then_saves_without_overwriting(store):
    bid = make("7")
    client("7").post(f"/business/{bid}/days", json={"day": "2026-09-13", "sales": 999})
    csv = b'Date,Orders,Net Sales\n13/09/2026,40,"12,400"\n14/09/2026,35,"10,050"\n20/09/2026,1,1\n'
    files = {"file": ("petpooja.csv", csv, "text/csv")}
    pre = client("7").post(f"/business/{bid}/import", files=files, data={"preview": "true"}).json()
    assert pre["saved"] is None and pre["future_skipped"] == 1 and pre["amount_col"] == "Net Sales"
    got = client("7").post(f"/business/{bid}/import", files=files).json()
    assert got["saved"] == {"added": 1, "replaced": 0, "kept": 1}
    assert {d["day"]: d["sales"] for d in db.days_for(bid)}["2026-09-13"] == 999
    bad = client("7").post(f"/business/{bid}/import", files={"file": ("x.csv", b"a,b\n1,2\n", "text/csv")})
    assert bad.status_code == 422


# ------------------------------------------------------------ chat tool and the alert

def test_tool_sets_up_logs_reads_back_and_forecasts(store):
    from harness.tools.builtin.business_tool import make_business_tool
    tool = make_business_tool("7")
    assert "action='setup'" in asyncio.run(tool.handler(action="log", sales=100))
    asyncio.run(tool.handler(action="setup", name="Chinar Café", kind="cafe", city="Srinagar"))
    b = db.first("7")
    seed(b["id"], 60)
    out = asyncio.run(tool.handler(action="log", sales=16400, bills=52))
    assert "Logged ₹16,400 · 52 bills" in out.text and "Tue 15 Sep" in out.text and out.ui["kind"] == "sales_logged"
    out = asyncio.run(tool.handler(action="log", sales=200, day="yesterday"))
    assert "yesterday" in out.text
    out = asyncio.run(tool.handler(action="forecast"))
    assert "Tomorrow (Wednesday) looks like about ₹" in out.text and out.ui["kind"] == "sales_forecast"
    assert "within" in out.text


def test_the_evening_alert_goes_out_once_and_at_most_twice_a_week(store, monkeypatch):
    from harness import push
    from harness.missions import slow_day

    async def no_mission(*a, **k):        # Pro gets a mission instead (test_missions.py); this is the plain alert
        return False

    monkeypatch.setattr(slow_day, "consider", no_mission)
    bid = make("7")
    seed(bid)
    sent = []

    async def fake_push(*a, **k):
        sent.append(a)
        return 1

    monkeypatch.setattr(push, "send", fake_push)
    monkeypatch.setattr(service, "_local_hour", lambda uid: 20)
    service._checked.clear()
    assert asyncio.run(service.evening_alerts()) == 1
    assert "Tomorrow looks slow for Chinar Café" in sent[0][2]
    assert asyncio.run(service.evening_alerts()) == 0            # once a day
    db.update("7", bid, nudged=[(TODAY - timedelta(days=1)).isoformat(), (TODAY - timedelta(days=2)).isoformat()])
    service._checked.clear()
    assert asyncio.run(service.evening_alerts()) == 0            # two this week already
    monkeypatch.setattr(service, "_local_hour", lambda uid: 9)
    db.update("7", bid, nudged=[])
    service._checked.clear()
    assert asyncio.run(service.evening_alerts()) == 0            # only in the evening


def test_free_gets_no_alert(store, monkeypatch):
    from harness import push
    bid = make("8")
    seed(bid)
    monkeypatch.setattr(push, "send", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no push on Free")))
    monkeypatch.setattr(service, "_local_hour", lambda uid: 20)
    service._checked.clear()
    assert asyncio.run(service.evening_alerts()) == 0


def test_the_plan_split():
    from harness.billing.plans import PLANS, gate_for
    assert gate_for("sales_forecast")[0] == "plus" and gate_for("sales_reasons")[0] == "pro"
    assert gate_for("sales_ideas")[0] == "pro" and gate_for("sales_whatsapp")[0] == "pro"
    assert PLANS["pro"].businesses_included == 5 and PLANS["plus"].businesses_included == 1
