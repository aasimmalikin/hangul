"""Missions (harness.missions): the slow-day job from the evening alert to the
result, the owner's go-ahead (page and WhatsApp), learning which ideas work,
earned autonomy and undo, expiry, the monthly outcome report, the plan gate
and per-user isolation."""
import asyncio
from datetime import date, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from harness import push
from harness.api.auth import get_current_user
from harness.api.routes import missions as routes
from harness.billing import entitlements
from harness.db import billing as billing_db
from harness.db import brands as brands_db
from harness.db import launch as launch_db
from harness.db import missions as db
from harness.db import sales as sales_db
from harness.db.models import (
    Brand,
    BrandAsset,
    BrandPost,
    Business,
    BusinessDay,
    BusinessEvent,
    LaunchPlan,
    Mission,
    MissionTrust,
    User,
)
from harness.missions import engine, learning, report, slow_day
from harness.sales import playbook, service
from harness.tools.builtin import files


@compiles(JSONB, "sqlite")
def _jsonb_as_json(_type, _compiler, **_kw):
    return "JSON"


TODAY = date(2026, 9, 15)                 # Tuesday; the slow day is Wednesday
TOMORROW = TODAY + timedelta(days=1)


class Clock:
    day = TODAY
    hour = 20


@pytest.fixture
def store(monkeypatch, tmp_path):
    engine_ = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    for m in (Business, BusinessDay, BusinessEvent, User, Brand, BrandAsset, BrandPost, LaunchPlan, Mission, MissionTrust):
        m.__table__.create(engine_)
    maker = sessionmaker(engine_)
    for mod in (sales_db, billing_db, brands_db, launch_db, db):
        monkeypatch.setattr(mod, "SessionLocal", maker)
    with maker() as s:
        s.add_all([User(id=7, plan="pro", plan_region="in"), User(id=8, plan="pro"), User(id=9, plan="plus")])
        s.commit()
    monkeypatch.setattr(entitlements, "billing_enabled", lambda: True)
    monkeypatch.setattr(files, "SESSIONS", tmp_path)
    Clock.day, Clock.hour = TODAY, 20
    monkeypatch.setattr(service, "local_today", lambda uid: Clock.day)
    monkeypatch.setattr(service, "_local_hour", lambda uid: Clock.hour)
    sent: list[tuple] = []

    async def fake_push(user_id, title, body, **kw):
        sent.append((user_id, body, kw.get("url")))
        return 1

    monkeypatch.setattr(push, "send", fake_push)
    return sent


def client(user="7"):
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[get_current_user] = lambda: {"user_id": user}
    return TestClient(app)


def business(user="7", brand=True) -> dict:
    brand_id = None
    if brand:
        brand_id = brands_db.create(user, name="Chinar Café", colors=[
            {"role": "primary", "hex": "#A8402C"}, {"role": "secondary", "hex": "#FFF6EC"},
            {"role": "accent", "hex": "#E3A72F"}, {"role": "text", "hex": "#1E1E1E"}]).id
    return sales_db.create(user, name="Chinar Café", kind="cafe", city="Srinagar", brand_id=brand_id)


def start(user: str, b: dict, day: date = TOMORROW, ideas=None) -> dict:
    ideas = ideas or playbook.suggest("cafe", ["rain"], day, price=320, plan_assumptions=None)
    data = {"business_name": b["name"], "weekday": day.strftime("%A"),
            "forecast": {"value": 9000, "low": 8000, "high": 10000, "typical": 13000, "accuracy": 0.08},
            "breakeven": None, "why": "below_usual", "ideas": ideas, "avg_bill": 320, "brand_id": b.get("brand_id")}
    m = asyncio.run(engine.begin(user, slow_day.KIND, day, data, business_id=b["id"]))
    assert m is not None
    return m


def log(b: dict, day: date, sales: float):
    sales_db.log_day(b["id"], day, sales=sales, source="page")


def events(b: dict, kind: str, day: date = TOMORROW) -> list:
    return [e for e in sales_db.events(b["id"], kind, day) if e["day"] == day.isoformat()]


# ------------------------------------------------------------ the whole job

def test_a_slow_day_goes_from_alert_to_result(store, monkeypatch):
    from tests.unit.test_sales import seed
    b = business()
    seed(b["id"])

    async def fake_geo(city):
        return (34.08, 74.8)

    async def fake_days(lat, lon, s, e, today):
        from tests.unit.test_sales import rain_on
        out, d = {}, s
        while d <= e:
            out[d] = (rain_on(d), 24.0)
            d += timedelta(days=1)
        return out

    monkeypatch.setattr(service.weather, "geocode", fake_geo)
    monkeypatch.setattr(service.weather, "days", fake_days)
    service._checked.clear()

    # 1-3: the evening alert starts the mission, which prepares the post and asks once
    assert asyncio.run(service.evening_alerts()) == 1
    [m] = db.list_for("7")
    assert m["status"] == "waiting" and [s["state"] for s in m["steps"]] == ["done", "done", "waiting", "todo", "todo"]
    assert m["steps"][0]["label"] == "Spotted Wednesday looks slow"
    assert m["data"]["post_id"] and all((files.SESSIONS / "7" / f).is_file() for f in m["data"]["files"])
    assert brands_db.get_post("7", m["data"]["post_id"]).sizes == ["post", "story"]
    assert len(store) == 1 and "Shall I go ahead?" in store[0][1] and store[0][2] == f"/missions/{m['id']}"
    assert not any("Tomorrow looks slow for" in s[1] for s in store)       # the mission replaced the plain alert
    service._checked.clear()
    assert asyncio.run(service.evening_alerts()) == 0                       # once a day, never twice

    # the go-ahead, from the page
    r = client().post(f"/missions/{m['id']}/decide", json={"decision": "approve"})
    assert r.status_code == 200, r.text
    assert "Forward this to your regulars" in r.json()["message"]
    assert events(b, "idea_used") and r.json()["status"] == "active"
    assert client().post(f"/missions/{m['id']}/decide", json={"decision": "approve"}).status_code == 409

    # 4: nothing until the evening of the day itself
    asyncio.run(engine.tick())
    assert db.get("7", m["id"])["steps"][3]["state"] == "todo"
    Clock.day, Clock.hour = TOMORROW, 20
    asyncio.run(engine.tick())
    assert any("How did Chinar Café do today?" in s[1] for s in store)
    assert db.get("7", m["id"])["steps"][3]["state"] == "done"

    # 5: the day is logged above the forecast's range -> it worked, and it's remembered
    f = db.get("7", m["id"])["data"]["forecast"]
    log(b, TOMORROW, f["high"] + 2000)
    asyncio.run(engine.tick())
    done = db.get("7", m["id"])
    assert done["status"] == "done" and done["data"]["outcome"]["verdict"] == "worked"
    assert "worked" in store[-1][1]
    assert learning.stats(b["id"])[done["data"]["idea"]["key"]]["tries"] == 1


def test_plus_gets_a_mission_for_its_weekly_idea_and_free_gets_none(store, monkeypatch):
    from tests.unit.test_sales import rain_on, seed

    async def fake_geo(city):
        return (34.08, 74.8)

    async def fake_days(lat, lon, s, e, today):
        out, d = {}, s
        while d <= e:
            out[d] = (rain_on(d), 24.0)
            d += timedelta(days=1)
        return out

    monkeypatch.setattr(service.weather, "geocode", fake_geo)
    monkeypatch.setattr(service.weather, "days", fake_days)
    plus = business("9", brand=False)
    seed(plus["id"])
    service._checked.clear()
    asyncio.run(service.evening_alerts())
    [m] = db.list_for("9")
    assert m["status"] == "waiting" and len(m["data"]["ideas"]) == 1        # Plus: this week's one idea

    # going ahead uses this week's idea, so the next slow day this week gets the plain alert instead
    assert client("9").post(f"/missions/{m['id']}/decide", json={"decision": "approve"}).status_code == 200
    assert service.ideas_left(plus["id"], TODAY) == 0

    with sales_db.SessionLocal() as s:
        s.get(User, 8).plan = "free"
        s.commit()
    free = business("8", brand=False)
    seed(free["id"])
    service._checked.clear()
    asyncio.run(service.evening_alerts())
    assert db.list_for("8") == []


def test_without_a_brand_the_idea_still_comes_in_words(store):
    b = business(brand=False)
    m = start("7", b)
    assert m["status"] == "waiting" and m["data"]["post_id"] is None
    assert "Link a brand" in m["steps"][1]["note"] and m["data"]["share_text"]


# ------------------------------------------------------------ deciding, expiry, undo, trust

def test_not_this_time_cancels_and_resets_the_streak(store):
    b = business()
    db.set_trust("7", slow_day.scope(b["id"]), streak=2)
    m = start("7", b)
    r = client().post(f"/missions/{m['id']}/decide", json={"decision": "reject"})
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    assert db.trust("7", slow_day.scope(b["id"]))["streak"] == 0
    assert events(b, "idea_used") == []


def test_an_unanswered_go_ahead_expires_on_the_day_at_two(store):
    b = business()
    m = start("7", b)
    Clock.day, Clock.hour = TOMORROW, 11
    asyncio.run(engine.tick())
    assert db.get("7", m["id"])["status"] == "waiting"                     # the morning is still useful
    Clock.hour = 14
    asyncio.run(engine.tick())
    gone = db.get("7", m["id"])
    assert gone["status"] == "expired" and all(s["state"] != "todo" for s in gone["steps"])
    r = client().post(f"/missions/{m['id']}/decide", json={"decision": "approve"})
    assert r.status_code == 409


def test_trust_is_earned_offered_once_and_can_be_taken_back(store):
    b = business()
    for i in range(slow_day.TRUST_AFTER):
        m = start("7", b, TOMORROW + timedelta(days=7 * i))
        _, reply = asyncio.run(slow_day.decide("7", m["id"], True))
    assert db.trust("7", slow_day.scope(b["id"]))["offered"]
    assert db.get("7", m["id"])["data"]["trust_offer"]
    # a fourth go-ahead doesn't offer again
    m4 = start("7", b, TOMORROW + timedelta(days=28))
    asyncio.run(slow_day.decide("7", m4["id"], True))
    assert not db.get("7", m4["id"])["data"].get("trust_offer")

    # the owner says yes (WhatsApp button) -> the next slow day goes ahead on its own
    reply, _ = asyncio.run(slow_day.on_button("7", f"auto:{m['id']}"))
    assert "I'll go ahead" in reply
    day = TOMORROW + timedelta(days=35)
    auto = start("7", b, day)
    assert auto["status"] == "active" and auto["data"]["auto"] and auto["steps"][2]["state"] == "done"
    assert any("I've gone ahead" in s[1] and "Undo it here" in s[1] for s in store)
    assert events(b, "idea_used", day)

    # undo takes the offer back and returns to asking first
    r = client().post(f"/missions/{auto['id']}/undo")
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    assert events(b, "idea_used", day) == [] and events(b, "offer", day) == []
    assert db.trust("7", slow_day.scope(b["id"])) | {"scope": ""} == {"scope": "", "streak": 0, "auto": False, "offered": True}

    # and the page can switch it on or off
    assert client().put(f"/missions/trust/{b['id']}", json={"auto": True}).json()["auto"] is True
    assert client().put("/missions/trust/999", json={"auto": True}).status_code == 404


def test_whatsapp_buttons_decide_once(store):
    b = business()
    m = start("7", b)
    _, buttons = slow_day.question(m)
    assert buttons == [(f"mis:ok:{m['id']}", "Go ahead"), (f"mis:no:{m['id']}", "Not this time")]
    reply, _ = asyncio.run(slow_day.on_button("7", f"ok:{m['id']}"))
    assert reply.startswith("Done. For Wednesday")
    again, _ = asyncio.run(slow_day.on_button("7", f"ok:{m['id']}"))
    assert again == "That was already decided."
    other, _ = asyncio.run(slow_day.on_button("8", f"ok:{m['id']}"))         # someone else's mission
    assert other == "I couldn't find that one."


def test_whatsapp_choice_routes_mission_buttons(store, monkeypatch):
    from harness.whatsapp import service as wa
    from harness.whatsapp.inbound import Inbound
    b = business()
    m = start("7", b)
    said = []

    async def fake_say(phone, text, user_id=None, *, markdown=True):
        said.append(text)
        return 1

    monkeypatch.setattr(wa, "say", fake_say)
    link = type("L", (), {"user_id": "7"})()
    msg = Inbound(wamid="w1", phone="919999999999", kind="choice", text="Go ahead", reply_id=f"mis:ok:{m['id']}")
    asyncio.run(wa._choice(msg, link))
    assert said and said[0].startswith("Done.") and db.get("7", m["id"])["data"]["approved"]


# ------------------------------------------------------------ measuring and learning

def test_measuring_is_honest_about_the_forecast_error():
    f = {"value": 9000, "low": 8000, "high": 10000}
    assert slow_day.judge(11000, f)["verdict"] == "worked"
    assert slow_day.judge(9500, f)["verdict"] == "helped"          # inside the range: maybe noise
    assert slow_day.judge(8500, f) | {} == {"actual": 8500, "expected": 9000, "lift": -500, "lift_pct": -0.056,
                                            "verdict": "no_effect"}


def test_no_sales_logged_means_no_verdict(store):
    b = business()
    m = start("7", b)
    asyncio.run(slow_day.decide("7", m["id"], True))
    Clock.day = TOMORROW + timedelta(days=slow_day.GRACE_DAYS + 1)
    asyncio.run(engine.tick())
    gone = db.get("7", m["id"])
    assert gone["status"] == "done" and "outcome" not in gone["data"]
    assert "couldn't tell" in gone["steps"][4]["note"]


def test_ideas_that_worked_here_come_first_and_flops_last(store):
    b = business(brand=False)
    ideas = playbook.suggest("cafe", ["rain", "weekday"], TOMORROW, price=320, plan_assumptions=None)
    first, second = ideas[0]["key"], ideas[1]["key"]
    for i, (key, pct) in enumerate([(first, -0.2), (second, 0.15), (second, 0.05)]):
        m = start("7", b, TOMORROW + timedelta(days=i), ideas=[x for x in ideas if x["key"] == key] + ideas)
        db.save(m["id"], status="done", data={"idea": {"key": key, "title": key}, "approved": True,
                                              "outcome": {"lift_pct": pct, "lift": pct * 9000, "verdict": "helped"}})
    ranked = learning.rank(b["id"], ideas)
    keys = [i["key"] for i in ranked]
    assert keys[0] == second and keys[-1] == first
    assert ranked[0]["track_note"] == "Tried 2 times here: on average 10% above my forecast."
    assert "without a clear lift" in ranked[-1]["track_note"]


# ------------------------------------------------------------ the month in rupees

def test_the_monthly_report_counts_only_what_ran_and_was_measured(store):
    b = business(brand=False)
    worked = start("7", b, date(2026, 9, 2))
    db.save(worked["id"], status="done", data={"approved": True, "outcome": {"lift": 3200, "lift_pct": 0.3, "verdict": "worked"}})
    flat = start("7", b, date(2026, 9, 9))
    db.save(flat["id"], status="done", data={"approved": True, "auto": True, "outcome": {"lift": -400, "lift_pct": -0.04, "verdict": "no_effect"}})
    no = start("7", b, date(2026, 9, 16))
    db.save(no["id"], status="cancelled", data={"approved": False})
    start("7", b, date(2026, 10, 1))                                  # next month: not counted
    s = report.summary("7", date(2026, 9, 1))
    assert (s["spotted"], s["went_ahead"], s["on_their_own"], s["measured"], s["lift"]) == (3, 2, 1, 2, 2800)
    assert s["best"]["lift"] == 3200 and s["price"] == "Pro costs you ₹1,499"
    t = report.text(s)
    assert "3 slow days spotted, 2 offers run (1 on my own)" in t and "₹2,800 more" in t and "₹1,499" in t

    # sent once on the 1st, from 9 am
    Clock.day, Clock.hour = date(2026, 10, 1), 8
    assert asyncio.run(report.due()) == 0
    Clock.hour = 9
    assert asyncio.run(report.due()) == 1
    assert asyncio.run(report.due()) == 0
    assert any(s[1].startswith("*September with Hangul*") for s in store)
    r = client().get("/missions/report", params={"month": "2026-09"})
    assert r.status_code == 200 and r.json()["lift"] == 2800


# ------------------------------------------------------------ plans and isolation

def test_missions_are_plus_and_up_and_private(store):
    b = business()
    m = start("7", b)
    assert client("8").get(f"/missions/{m['id']}").status_code == 404
    assert client("8").post(f"/missions/{m['id']}/decide", json={"decision": "approve"}).status_code == 404
    assert client("8").get("/missions").json()["missions"] == []
    page = client().get("/missions").json()
    assert page["allowed"] and [x["id"] for x in page["missions"]] == [m["id"]]
    # after a downgrade to Free: no go-ahead, but the plan check comes first and nothing changes
    with sales_db.SessionLocal() as s:
        s.get(User, 7).plan = "free"
        s.commit()
    r = client().post(f"/missions/{m['id']}/decide", json={"decision": "approve"})
    assert r.status_code == 402 and r.json()["detail"]["plan_needed"] == "plus"
    assert db.get("7", m["id"])["status"] == "waiting"
    assert client().put(f"/missions/trust/{b['id']}", json={"auto": False}).status_code == 200


def test_a_broken_step_stops_the_mission_without_stopping_the_scheduler(store, monkeypatch):
    b = business(brand=False)

    async def boom(ctx):
        raise RuntimeError("disk full")

    monkeypatch.setitem(slow_day.TEMPLATE.run, "prepare", boom)
    m = start("7", b)
    assert m["status"] == "done" and m["steps"][1]["state"] == "failed" and m["data"]["failed_step"] == "prepare"
    assert asyncio.run(engine.tick()) == 0
