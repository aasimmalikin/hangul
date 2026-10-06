"""Approve-by-link for scheduled tasks: the signed token (round trip, tampering,
expiry), the card wording, the public routes (show is harmless, decide goes through
/approve and works once), and the email that carries it."""
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from harness import approval_links as al
from harness.api.routes import approval_links as routes
from harness.api.routes import approve as approve_route
from harness.approval_card import card, one_line
from harness.notify import task_email

EVENT = {"name": "calendar__create_event", "tool_call_id": "c1",
         "arguments": {"summary": "Hangul test", "start": "2026-10-06T17:15:00+05:30", "end": "2026-10-06T17:30:00+05:30"}}


def test_a_link_names_one_run_of_one_user_and_cannot_be_forged_or_reused_late():
    token = al.make("run-1", "3", now=1_000)
    assert al.read(token, now=1_001) == ("run-1", "3")
    payload, sig = token.split(".")
    other = al.make("run-2", "3", now=1_000).split(".")[0]
    for bad in (f"{other}.{sig}", f"{payload}.{sig[:-2]}AA", "nonsense", ""):
        with pytest.raises(al.LinkError):
            al.read(bad, now=1_001)
    with pytest.raises(al.LinkError):
        al.read(token, now=1_000 + al.TTL_S + 1)                  # expires with the action


def test_the_card_says_what_will_happen():
    c = card(EVENT)
    assert c["title"] == "Add an event to your calendar?"
    assert ["Event", "Hangul test"] in c["rows"]
    assert ["When", "Tue 6 Oct, 5:15 PM – 5:30 PM"] in c["rows"]
    assert ["Invites", "Nobody — only your calendar"] in c["rows"]
    mail = card({"name": "gmail__send_message", "arguments": {"to": "boss@x.com", "subject": "Q3", "body": "Hi"}})
    assert ["To", "boss@x.com"] in mail["rows"] and mail["body"] == "Hi"
    assert one_line(EVENT) == "Add an event to your calendar? Hangul test · Tue 6 Oct, 5:15 PM – 5:30 PM"


@pytest.fixture
def client(monkeypatch):
    runs = {"run-1": SimpleNamespace(user_id="3", status="pending_approval", pending_tool=EVENT,
                                     conversation_id="c9", message=[{"role": "user", "content": "Find a slot"}])}
    monkeypatch.setattr(approve_route._store, "load", lambda rid: runs.get(rid))
    decided = []

    async def approve(req, user):
        if req.approval_id in decided:
            raise HTTPException(status_code=404, detail="No pending action for that approval id.")
        decided.append(req.approval_id)
        return SimpleNamespace(answer="Added Hangul test.", pending_tool=None, conversation_id="c9")
    monkeypatch.setattr(approve_route, "approve", approve)
    app = FastAPI()
    app.include_router(routes.router)
    return TestClient(app), runs, decided


def test_opening_the_link_only_shows_the_action(client):
    c, _, decided = client
    r = c.get(f"/approval-links/{al.make('run-1', '3')}")
    assert r.status_code == 200 and r.json()["state"] == "waiting" and decided == []
    assert r.json()["card"]["title"] == "Add an event to your calendar?" and r.json()["asked"] == "Find a slot"


def test_a_link_for_someone_else_or_a_bad_link_shows_nothing(client):
    c, _, _ = client
    assert c.get(f"/approval-links/{al.make('run-1', '4')}").status_code == 410     # not their run
    assert c.get("/approval-links/garbage").status_code == 410
    assert c.post("/approval-links/garbage", json={"decision": "approve"}).status_code == 410


def test_deciding_works_once(client):
    c, _, decided = client
    token = al.make("run-1", "3")
    r = c.post(f"/approval-links/{token}", json={"decision": "approve"})
    assert r.json() == {"state": "approved", "answer": "Added Hangul test.", "waiting_again": False,
                        "conversation_id": "c9"}
    assert c.post(f"/approval-links/{token}", json={"decision": "approve"}).json()["state"] == "decided"
    assert decided == ["run-1"]
    assert c.post(f"/approval-links/{token}", json={"decision": "maybe"}).status_code == 422


def test_an_expired_action_says_so(client, monkeypatch):
    c, runs, _ = client

    async def approve(req, user):
        raise HTTPException(status_code=409, detail="expired", headers={"X-Reason": "approval_expired"})
    monkeypatch.setattr(approve_route, "approve", approve)
    assert c.post(f"/approval-links/{al.make('run-1', '3')}", json={"decision": "approve"}).json()["state"] == "expired"
    runs["run-1"].status = "expired"
    assert c.get(f"/approval-links/{al.make('run-1', '3')}").json() == {
        "state": "expired", "asked": "Find a slot", "card": None, "conversation_id": "c9"}


def test_the_email_carries_the_card_and_both_buttons():
    link = "https://hangul.app/approve/tok"
    subject, plain, html = task_email("Test", "Found 5:15 PM.", needs_approval=True,
                                      approval={"card": card(EVENT), "url": link})
    assert subject == "⏰ Test — needs your OK"
    assert f"{link}?d=approve" in html and f"{link}?d=reject" in html and "Hangul test" in html
    assert link in plain and "Add an event to your calendar?" in plain
    _, _, html = task_email("x", "y", approval={"card": card({"name": "gmail__send_message", "arguments": {
        "to": "a@b.c", "subject": "<script>", "body": "<b>hi</b>"}}), "url": link})
    assert "<script>" not in html and "&lt;script&gt;" in html                # escaped
