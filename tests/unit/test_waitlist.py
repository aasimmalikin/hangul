"""Pre-registration (/join): an email joins once, joining again never reveals it
was already there, bad input is a clear 422, and the operator gets counts."""
import io

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from harness.api.routes import waitlist as routes
from harness.db import base as db_base
from harness.db import waitlist as wl
from harness.db.models import WaitlistEntry


@pytest.fixture
def db(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    WaitlistEntry.__table__.create(engine)
    maker = sessionmaker(engine)
    monkeypatch.setattr(db_base, "SessionLocal", maker)
    return maker


@pytest.fixture
def client(db):
    app = FastAPI()
    app.include_router(routes.router)
    return TestClient(app)


def test_an_email_joins_once_lower_cased(db):
    wl.join("  Priya@Example.COM ", "founder", "pro", "X")
    wl.join("priya@example.com")
    with db() as s:
        rows = s.query(WaitlistEntry).all()
    assert [(r.email, r.persona, r.interest, r.source) for r in rows] == [("priya@example.com", "founder", "pro", "x")]


def test_joining_again_fills_blanks_but_never_overwrites(db):
    wl.join("sam@example.com")
    wl.join("sam@example.com", "student", "plus")
    wl.join("sam@example.com", "founder", "pro")
    with db() as s:
        r = s.query(WaitlistEntry).one()
    assert (r.persona, r.interest) == ("student", "plus")


@pytest.mark.parametrize("email", ["", "no-at-sign", "a@b", "two@@example.com", "spa ce@example.com", "x" * 250 + "@example.com"])
def test_bad_emails_are_refused(db, email):
    with pytest.raises(ValueError, match="email"):
        wl.join(email)


def test_unknown_persona_or_plan_is_refused(db):
    with pytest.raises(ValueError, match="persona"):
        wl.join("a@example.com", persona="wizard")
    with pytest.raises(ValueError, match="interest"):
        wl.join("a@example.com", interest="enterprise")
    with pytest.raises(ValueError, match="trade"):
        wl.join("a@example.com", trade="spaceport")


def test_source_is_reduced_to_a_safe_tag():
    assert wl.clean_source("  X.com/<script>  ") == "x.comscript"
    assert len(wl.clean_source("a" * 100)) == 40


def test_the_endpoint_answers_the_same_for_new_and_existing_emails(client):
    first = client.post("/waitlist", json={"email": "lee@example.com", "persona": "founder"})
    again = client.post("/waitlist", json={"email": "LEE@example.com"})
    assert first.status_code == again.status_code == 200
    assert first.json() == again.json() == {"ok": True, "total": 1}
    assert client.get("/waitlist/count").json() == {"total": 1}


def test_the_endpoint_explains_bad_input(client):
    r = client.post("/waitlist", json={"email": "not-an-email"})
    assert r.status_code == 422 and "email" in r.json()["detail"]
    r = client.post("/waitlist", json={"email": "ok@example.com", "interest": "gold"})
    assert r.status_code == 422 and "Plus" in r.json()["detail"]


def test_summary_and_export(db):
    wl.join("a@example.com", "founder", "pro", "x", trade="cafe", city="Pune")
    wl.join("b@example.com", "student", "", "x", trade="salon", city=" pune ")
    wl.join("c@example.com")
    s = wl.summary()
    assert s["total"] == 3 and s["last_7_days"] == 3
    assert s["by_trade"] == {"cafe": 1, "salon": 1, "unknown": 1}
    assert s["by_city"] == {"pune": 2, "unknown": 1}
    assert s["by_persona"] == {"founder": 1, "student": 1, "unknown": 1}
    assert s["by_interest"] == {"pro": 1, "unknown": 2}
    assert s["by_source"] == {"x": 2, "unknown": 1}
    out = io.StringIO()
    assert wl.export(out) == 3
    lines = out.getvalue().splitlines()
    assert lines[0] == "email,trade,city,persona,interest,source,joined_at"
    assert lines[1].startswith("a@example.com,cafe,Pune,founder,pro,x,")
