"""WhatsApp: the webhook (verification, signature, parsing), formatting, the
message flows (linking, plans, the agent, approvals, choices, the waiting
brief), notifications in and out of the 24-hour window, the link table, and
the vault's binary media download. Everything Meta-side is faked."""
import asyncio
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from harness.api.auth import get_current_user
from harness.api.routes import whatsapp as wa_route
from harness.db import whatsapp as wa_db
from harness.whatsapp import client, service
from harness.whatsapp.fmt import one_line, split, to_whatsapp
from harness.whatsapp.inbound import Inbound, parse, signature_ok

SECRET = "app-secret"


def signed(payload: dict) -> tuple[bytes, dict]:
    raw = json.dumps(payload).encode()
    return raw, {"X-Hub-Signature-256": "sha256=" + hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest(),
                 "Content-Type": "application/json"}


def delivery(*messages, statuses=()) -> dict:
    return {"object": "whatsapp_business_account", "entry": [{"changes": [{"field": "messages", "value": {
        "messaging_product": "whatsapp", "contacts": [{"wa_id": "919876543210", "profile": {"name": "Aasim"}}],
        "messages": list(messages), "statuses": list(statuses)}}]}]}


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "EAAG-test")
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "1234567890")
    monkeypatch.setenv("WHATSAPP_APP_SECRET", SECRET)
    monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN", "verify-me")
    monkeypatch.setenv("WHATSAPP_BUSINESS_NUMBER", "+91 90000 00000")


# ------------------------------------------------------------------ webhook basics

def test_signature():
    raw = b'{"a":1}'
    good = "sha256=" + hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest()
    assert signature_ok(raw, good, SECRET)
    assert not signature_ok(raw + b" ", good, SECRET)
    assert not signature_ok(raw, good, None) and not signature_ok(raw, None, SECRET)


def test_parse_every_kind_and_ignore_statuses():
    msgs = parse(delivery(
        {"from": "919876543210", "id": "w1", "type": "text", "text": {"body": "hi"}},
        {"from": "919876543210", "id": "w2", "type": "interactive",
         "interactive": {"type": "button_reply", "button_reply": {"id": "ok:run-1", "title": "Approve"}}},
        {"from": "919876543210", "id": "w3", "type": "interactive",
         "interactive": {"type": "list_reply", "list_reply": {"id": "pick:run-1:4", "title": "Friday"}}},
        {"from": "919876543210", "id": "w4", "type": "audio", "audio": {"id": "m1", "mime_type": "audio/ogg", "voice": True}},
        {"from": "919876543210", "id": "w5", "type": "document",
         "document": {"id": "m2", "filename": "bill.pdf", "mime_type": "application/pdf", "caption": "pay this"}},
        {"from": "919876543210", "id": "w6", "type": "sticker", "sticker": {"id": "s"}},
        statuses=[{"id": "w0", "status": "delivered"}]))
    assert [(m.kind, m.text, m.reply_id) for m in msgs] == [
        ("text", "hi", None), ("choice", "Approve", "ok:run-1"), ("choice", "Friday", "pick:run-1:4"),
        ("audio", "", None), ("document", "pay this", None), ("unsupported", "", None)]
    assert msgs[0].name == "Aasim" and msgs[0].phone == "919876543210" and msgs[4].filename == "bill.pdf"


def test_markdown_becomes_whatsapp_text():
    md = "## Today\n**Standup** at 10\n- *call* Priya\n[Docs](https://x.com)\n| a | b |\n|---|---|\n| 1 | 2 |"
    out = to_whatsapp(md)
    assert "*Today*" in out and "*Standup*" in out and "• _call_ Priya" in out
    assert "Docs (https://x.com)" in out and "1 · 2" in out and "---" not in out
    assert "```x = 1```" in to_whatsapp("```python\nx = 1\n```")


def test_long_answers_are_split_and_numbered():
    parts = split("para one.\n\n" + ("word " * 1500), limit=3900)
    assert len(parts) == 2 and parts[0].endswith("(1/2)") and all(len(p) <= 3910 for p in parts)
    assert split("short") == ["short"]
    assert one_line("a\n\tb    c" + "x" * 300, 50).endswith("…") and "\n" not in one_line("a\nb")


def _app(user_id="7"):
    app = FastAPI()
    app.include_router(wa_route.router)
    app.dependency_overrides[get_current_user] = lambda: {"user_id": user_id}
    return TestClient(app)


def test_meta_verification(on):
    c = _app()
    ok = c.get("/whatsapp/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "verify-me", "hub.challenge": "42"})
    assert ok.status_code == 200 and ok.text == "42"
    assert c.get("/whatsapp/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "no", "hub.challenge": "1"}).status_code == 403


def test_webhook_checks_the_signature_and_hands_messages_off(on, monkeypatch):
    seen = []

    async def handle(msg):
        seen.append(msg.wamid)
    monkeypatch.setattr(service, "handle", handle)
    c = _app()
    raw, headers = signed(delivery({"from": "919876543210", "id": "w1", "type": "text", "text": {"body": "hi"}}))
    assert c.post("/whatsapp/webhook", content=raw, headers={**headers, "X-Hub-Signature-256": "sha256=bad"}).status_code == 401
    assert c.post("/whatsapp/webhook", content=raw, headers=headers).json() == {"ok": True}
    assert seen == ["w1"]


def test_link_routes(on, monkeypatch):
    monkeypatch.setattr(wa_db, "start_link", lambda uid, ttl: "482913")
    monkeypatch.setattr(wa_db, "by_user", lambda uid: wa_db.Link("7", "919876543210", True, None, None, None))
    monkeypatch.setattr(wa_db, "unlink", lambda uid: True)
    c = _app()
    body = c.post("/whatsapp/link").json()
    assert body["message"] == "HANGUL 482913" and body["wa_link"] == "https://wa.me/919000000000?text=HANGUL%20482913"
    st = c.get("/whatsapp/link").json()
    assert st["linked"] is True and st["phone"] == "+91 ••••• 3210" and st["chat_link"] == "https://wa.me/919000000000"
    assert c.delete("/whatsapp/link").json() == {"unlinked": True}


def test_link_routes_when_whatsapp_is_off():
    c = _app()
    assert c.get("/whatsapp/link").json() == {"enabled": False, "linked": False}
    assert c.post("/whatsapp/link").status_code == 503


# ------------------------------------------------------------------ message flows

class FakeWA:
    """Records what Hangul sends; stands in for the client and the link table."""
    def __init__(self, monkeypatch, link=None, plan="plus"):
        self.sent: list[tuple] = []
        self.links: dict[str, wa_db.Link] = {}
        self.seen: set[str] = set()
        self.charged = 0
        if link:
            self.links[link.phone] = link
        for fn in ("send_text", "send_buttons", "send_list", "send_template"):
            monkeypatch.setattr(client, fn, self._rec(fn))
        # scheduled runs waiting on the user (none unless a test says so): no real DB
        self.waiting: list[tuple[str, str]] = []
        monkeypatch.setattr("harness.db.tasks.waiting_runs", lambda uid: self.waiting)

        async def mark_read(wamid, typing=True):
            pass
        monkeypatch.setattr(client, "mark_read", mark_read)
        monkeypatch.setattr(wa_db, "first_time", lambda w: not (w in self.seen or self.seen.add(w)))
        monkeypatch.setattr(wa_db, "by_phone", lambda p: self.links.get(p))
        monkeypatch.setattr(wa_db, "by_user", lambda u: next((lk for lk in self.links.values() if lk.user_id == u), None))
        monkeypatch.setattr(wa_db, "update", self._update)
        monkeypatch.setattr(service, "_chat_allowed", lambda uid: plan != "free")

        async def charge(uid, n):
            self.charged += n
        monkeypatch.setattr(service, "_charge", charge)

    def _rec(self, fn):
        async def send(*args):
            self.sent.append((fn, *args))
            return "wamid.out"
        return send

    def _update(self, uid, **fields):
        for lk in self.links.values():
            if lk.user_id == uid:
                for k, v in fields.items():
                    setattr(lk, k, v)

    def texts(self):
        return [a[2] for a in self.sent if a[0] == "send_text"]


def linked(conversation_id="conv-1", pending=None, last=None):
    return wa_db.Link("7", "919876543210", True, conversation_id, last or datetime.now(UTC), pending)


def text(body, wamid="w1"):
    return Inbound(wamid=wamid, phone="919876543210", text=body)


def fake_agent(monkeypatch, answer="Done.", pending=None, conversation_id="conv-1", raise_status=None):
    calls = []

    async def build_and_run(req, user_id):
        calls.append(req)
        if raise_status:
            raise HTTPException(status_code=raise_status, detail={"detail": "Nope."})
        return SimpleNamespace(result=SimpleNamespace(answer=answer, pending_tool=pending),
                               run=SimpleNamespace(run_id="run-1"), conversation_id=conversation_id)
    monkeypatch.setattr("harness.api.routes.ask._build_and_run", build_and_run)
    return calls


def test_a_message_from_an_unlinked_number_explains_how_to_link(monkeypatch):
    wa = FakeWA(monkeypatch)
    asyncio.run(service.handle(text("hello")))
    assert "isn't linked" in wa.texts()[0] and "/settings#whatsapp" in wa.texts()[0]


def test_sending_the_code_links_the_number(monkeypatch):
    wa = FakeWA(monkeypatch)
    claimed = []
    monkeypatch.setattr(wa_db, "claim_code", lambda code, phone: claimed.append((code, phone)) or "7")
    asyncio.run(service.handle(text("HANGUL 482913")))
    assert claimed == [("482913", "919876543210")] and "linked" in wa.texts()[0]


def test_a_retried_delivery_is_answered_once(monkeypatch):
    wa = FakeWA(monkeypatch, link=linked())
    calls = fake_agent(monkeypatch)
    asyncio.run(service.handle(text("hi", "same")))
    asyncio.run(service.handle(text("hi", "same")))
    assert len(calls) == 1 and wa.texts() == ["Done."]


def test_a_question_runs_the_agent_in_the_whatsapp_conversation(monkeypatch):
    wa = FakeWA(monkeypatch, link=linked(conversation_id=None))
    calls = fake_agent(monkeypatch, answer="**Standup** at 10", conversation_id="conv-new")
    asyncio.run(service.handle(text("what's on today?")))
    req = calls[0]
    assert (req.question, req.model, req.connectors_auto, req.conversation_id) == ("what's on today?", "auto", True, None)
    assert wa.texts() == ["*Standup* at 10"]
    assert wa.links["919876543210"].conversation_id == "conv-new"       # follow-ups continue this chat
    assert wa.charged == 1


def test_free_users_get_reminders_but_chatting_is_plus(monkeypatch):
    wa = FakeWA(monkeypatch, link=linked(), plan="free")
    calls = fake_agent(monkeypatch)
    asyncio.run(service.handle(text("hi")))
    assert calls == [] and "part of *Plus*" in wa.texts()[0]


def test_an_action_needing_approval_comes_with_buttons(monkeypatch):
    wa = FakeWA(monkeypatch, link=linked())
    fake_agent(monkeypatch, pending={"name": "gmail__send_message",
                                     "arguments": {"to": "priya@acme.com", "subject": "Hi", "body": "See you at 5"}})
    asyncio.run(service.handle(text("email priya")))
    kind, phone, body, buttons = wa.sent[0]
    assert kind == "send_buttons" and "Send this email?" in body and "priya@acme.com" in body
    assert buttons == [("ok:run-1", "Approve"), ("no:run-1", "Reject")]


@pytest.mark.parametrize("n,kind", [(2, "send_buttons"), (5, "send_list")])
def test_choices_become_buttons_or_a_list(monkeypatch, n, kind):
    wa = FakeWA(monkeypatch, link=linked())
    fake_agent(monkeypatch, pending={"name": "ask_user", "arguments": {
        "question": "Which day?", "options": [{"label": f"Day {i}", "description": "…"} for i in range(n)]}})
    asyncio.run(service.handle(text("book it")))
    assert wa.sent[0][0] == kind and wa.sent[0][2] == "Which day?"
    ids = [b[0] for b in wa.sent[0][3 if kind == "send_buttons" else 4]]
    assert ids[0] == "pick:run-1:0" and len(ids) == n


def test_tapping_approve_resumes_the_run(monkeypatch):
    wa = FakeWA(monkeypatch, link=linked())
    got = []

    async def approve(req, user):
        got.append((req.approval_id, req.decision, req.choice, user["user_id"]))
        return SimpleNamespace(run_id="run-1", answer="Sent.", pending_tool=None)
    monkeypatch.setattr("harness.api.routes.approve.approve", approve)
    asyncio.run(service.handle(Inbound(wamid="w9", phone="919876543210", kind="choice", text="Approve", reply_id="ok:run-1")))
    assert got == [("run-1", "approve", None, "7")] and wa.texts() == ["Sent."]


def test_picking_an_option_sends_its_full_label(monkeypatch):
    FakeWA(monkeypatch, link=linked())
    got = []
    cp = SimpleNamespace(pending_tool={"name": "ask_user", "arguments": {"options": [{"label": "Monday"}, {"label": "Friday afternoon at the office"}]}})
    monkeypatch.setattr("harness.api.routes.approve._store", SimpleNamespace(load=lambda rid: cp))

    async def approve(req, user):
        got.append(req.choice)
        return SimpleNamespace(run_id="run-1", answer="Booked.", pending_tool=None)
    monkeypatch.setattr("harness.api.routes.approve.approve", approve)
    asyncio.run(service.handle(Inbound(wamid="w9", phone="919876543210", kind="choice", text="Friday afternoon…", reply_id="pick:run-1:1")))
    assert got == ["Friday afternoon at the office"]


def test_a_waiting_brief_arrives_when_the_user_writes(monkeypatch):
    wa = FakeWA(monkeypatch, link=linked(pending="*Morning brief*\n\nSunny, 2 meetings."))
    calls = fake_agent(monkeypatch)
    asyncio.run(service.handle(text("brief")))
    assert wa.texts() == ["*Morning brief*\n\nSunny, 2 meetings."] and calls == []      # "brief" just shows it
    assert wa.links["919876543210"].pending_text is None


def test_a_waiting_task_comes_with_approve_and_reject(on, monkeypatch):
    """A scheduled run that needs the user: buttons at once inside the 24-hour window;
    outside it the template goes first and the buttons follow their reply."""
    event = {"name": "calendar__create_event", "arguments": {"summary": "Focus", "start": "16:10", "end": "16:30"}}
    wa = FakeWA(monkeypatch, link=linked())
    asyncio.run(service.notify("7", "task", "Prepared the event.", title="Test", pending=event, run_id="run-7"))
    buttons = [x for x in wa.sent if x[0] == "send_buttons"]
    assert len(buttons) == 1 and buttons[0][3] == [("ok:run-7", "Approve"), ("no:run-7", "Reject")]
    assert "Focus" in buttons[0][2]

    wa = FakeWA(monkeypatch, link=linked(last=datetime.now(UTC) - timedelta(hours=30)))
    monkeypatch.setattr("harness.db.settings.get_settings", lambda uid: SimpleNamespace(display_name="Aasim"))
    asyncio.run(service.notify("7", "task", "Prepared the event.", title="Test", pending=event, run_id="run-7"))
    assert [x[0] for x in wa.sent] == ["send_template"]                    # a template can't carry buttons

    # with an approval template set up, the card and its buttons go out at once, window or not
    monkeypatch.setenv("WHATSAPP_TEMPLATE_APPROVAL", "task_approval")
    asyncio.run(service.notify("7", "task", "Prepared the event.", title="Test", pending=event, run_id="run-7"))
    assert wa.sent[-1][:3] == ("send_template", "919876543210", "task_approval")
    assert wa.sent[-1][3][0] == "Test" and "Focus" in wa.sent[-1][3][1]
    assert wa.sent[-1][4] == ["ok:run-7", "no:run-7"]
    monkeypatch.delenv("WHATSAPP_TEMPLATE_APPROVAL")

    wa.waiting = [("Test", "run-7"), ("Old", "run-gone")]
    from harness.api.routes import approve as approve_route
    checkpoints = {"run-7": SimpleNamespace(status="pending_approval", pending_tool=event),
                   "run-gone": SimpleNamespace(status="expired", pending_tool=None)}
    monkeypatch.setattr(approve_route._store, "load", lambda rid: checkpoints.get(rid))
    fake_agent(monkeypatch)
    asyncio.run(service.handle(text("hi")))
    buttons = [x for x in wa.sent if x[0] == "send_buttons"]
    assert [b[3][0][0] for b in buttons] == ["ok:run-7"]                     # expired runs are skipped


def test_busy_and_plan_refusals_are_explained(monkeypatch):
    wa = FakeWA(monkeypatch, link=linked())
    fake_agent(monkeypatch, raise_status=409)
    asyncio.run(service.handle(text("hi", "a")))
    fake_agent(monkeypatch, raise_status=402)
    asyncio.run(service.handle(text("hi", "b")))
    assert "still working" in wa.texts()[0] and "Nope." in wa.texts()[1] and "/billing" in wa.texts()[1]


# ------------------------------------------------------------------ notifications

def test_notify_inside_and_outside_the_24_hour_window(on, monkeypatch):
    monkeypatch.setattr("harness.db.settings.get_settings", lambda uid: SimpleNamespace(display_name="Aasim Malik"))
    wa = FakeWA(monkeypatch, link=linked())
    assert asyncio.run(service.notify("7", "reminder", "Call mom")) is True
    assert wa.texts() == ["⏰ *Reminder:* Call mom"]

    wa.links["919876543210"].last_inbound_at = datetime.now(UTC) - timedelta(hours=30)
    asyncio.run(service.notify("7", "reminder", "Pay rent\nby Friday"))
    assert wa.sent[-1] == ("send_template", "919876543210", "reminder", ["Pay rent by Friday"])
    asyncio.run(service.notify("7", "task", "Sunny, 2 meetings.", title="Morning brief"))
    assert wa.sent[-1] == ("send_template", "919876543210", "morning_brief", ["Aasim"])
    assert wa.links["919876543210"].pending_text == "*Morning brief*\n\nSunny, 2 meetings."


def test_notify_is_plus_and_pro_only(on, monkeypatch):
    wa = FakeWA(monkeypatch, link=linked(), plan="free")       # Free: app notifications and email instead
    assert asyncio.run(service.notify("7", "reminder", "Call mom")) is False
    assert asyncio.run(service.notify("7", "task", "Sunny.", title="Morning brief")) is False
    assert wa.sent == [] and wa.charged == 0


def test_notify_does_nothing_when_off_or_unlinked(on, monkeypatch):
    FakeWA(monkeypatch)
    assert asyncio.run(service.notify("7", "reminder", "x")) is False
    monkeypatch.delenv("WHATSAPP_ACCESS_TOKEN")
    assert asyncio.run(service.notify("7", "reminder", "x")) is False


# ------------------------------------------------------------------ the link table (SQLite)

@pytest.fixture
def db(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from harness.db.models import WhatsAppInbound, WhatsAppLink
    engine = create_engine("sqlite://")
    WhatsAppLink.__table__.create(engine)
    WhatsAppInbound.__table__.create(engine)
    monkeypatch.setattr(wa_db, "SessionLocal", sessionmaker(engine))


def test_linking_codes(db):
    code = wa_db.start_link("7", 600)
    assert len(code) == 6 and wa_db.claim_code("000000" if code != "000000" else "111111", "919876543210") is None
    assert wa_db.claim_code(code, "919876543210") == "7"
    assert wa_db.claim_code(code, "919876543210") is None                      # used up
    lk = wa_db.by_phone("919876543210")
    assert lk.linked and lk.user_id == "7" and lk.window_open()
    # the same number linked by another account moves to it
    code8 = wa_db.start_link("8", 600)
    assert wa_db.claim_code(code8, "919876543210") == "8"
    assert wa_db.by_user("7").linked is False and wa_db.by_phone("919876543210").user_id == "8"
    assert wa_db.unlink("8") and wa_db.by_phone("919876543210") is None


def test_expired_codes_and_dedupe(db):
    code = wa_db.start_link("7", -1)
    assert wa_db.claim_code(code, "919876543210") is None
    assert wa_db.first_time("wamid.1") is True and wa_db.first_time("wamid.1") is False


# ------------------------------------------------------------------ vault media download

def test_vault_returns_raw_bytes_for_media():
    from harness.vault.crypto import FernetCipher, generate_master_key
    from harness.vault.grants import InMemoryGrantStore
    from harness.vault.redact import Redactor
    from harness.vault.store import InMemoryConsentStore, InMemoryCredentialStore
    from harness.vault.vault import SYSTEM, Vault
    audio = bytes(range(256)) * 10

    def upstream(request):
        assert request.headers["authorization"] == "Bearer EAAG-secret"
        return httpx.Response(200, content=audio, headers={"Content-Type": "audio/ogg"})

    async def scenario():
        v = Vault(cipher=FernetCipher(generate_master_key()), credentials=InMemoryCredentialStore(),
                  consents=InMemoryConsentStore(), grants=InMemoryGrantStore(), redactor=Redactor(),
                  http=httpx.AsyncClient(transport=httpx.MockTransport(upstream)), grant_ttl_s=60,
                  public_url="http://api.test")
        await v.import_system_credential("whatsapp_media", "EAAG-secret")
        r = await v.call(subject=SYSTEM, provider="whatsapp_media", method="GET",
                         path="/whatsapp_business/attachments/", query={"mid": "1"}, want_bytes=True)
        assert r.raw == audio and r.body == ""
    asyncio.run(scenario())
