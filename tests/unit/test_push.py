"""Web Push: which endpoints are accepted, the subscription table (SQLite), a real
encrypt-and-sign round trip against a fake push service, forgetting gone
devices, the routes, and the scheduler notifying devices (and WhatsApp only on
Plus and Pro)."""
import asyncio
import base64
import json
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import FastAPI
from fastapi.testclient import TestClient

from harness import push
from harness.api.auth import get_current_user
from harness.api.routes import push as push_route
from harness.db import push as push_db

FCM = "https://fcm.googleapis.com/fcm/send/abc123"
APPLE = "https://web.push.apple.com/QGx1"


def b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


@pytest.fixture
def db(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from harness.db.models import PushSubscription
    # one shared in-memory database: sends look devices up from worker threads
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    PushSubscription.__table__.create(engine)
    monkeypatch.setattr(push_db, "SessionLocal", sessionmaker(engine))


@pytest.fixture
def on(monkeypatch):
    pub, priv = push.make_keys()
    monkeypatch.setenv("VAPID_PUBLIC_KEY", pub)
    monkeypatch.setenv("VAPID_PRIVATE_KEY", priv)
    monkeypatch.setenv("VAPID_SUBJECT", "mailto:ops@example.com")
    return pub


class Browser:
    """A browser's side of a subscription: its own key pair and auth secret."""
    def __init__(self, endpoint=FCM):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.auth = b"0123456789abcdef"
        self.endpoint = endpoint
        pub = self.key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        self.p256dh = b64(pub)

    def decrypt(self, body: bytes) -> dict:
        import http_ece
        return json.loads(http_ece.decrypt(body, private_key=self.key, auth_secret=self.auth, version="aes128gcm"))


class PushService:
    """Stands in for FCM/Apple: records each POST, answers with ``status``."""
    def __init__(self, monkeypatch, status=201):
        self.calls, self.status = [], status
        import pywebpush
        monkeypatch.setattr(pywebpush.requests, "post", self.post)

    def post(self, url, data=None, headers=None, timeout=None):
        self.calls.append(SimpleNamespace(url=url, data=data, headers=headers))
        return SimpleNamespace(status_code=self.status, text="", reason="", headers={})


# ------------------------------------------------------------------ endpoints

@pytest.mark.parametrize("url,ok", [
    (FCM, True), (APPLE, True),
    ("https://updates.push.services.mozilla.com/wpush/v2/x", True),
    ("https://wns2-par02p.notify.windows.com/w/?token=x", True),
    ("http://fcm.googleapis.com/fcm/send/x", False),                 # not https
    ("https://fcm.googleapis.com:8443/fcm/send/x", False),           # odd port
    ("https://fcm.googleapis.com.evil.example/x", False),            # look-alike
    ("https://169.254.169.254/latest/meta-data", False),             # the server's own network
    ("https://localhost/x", False), ("not a url", False),
])
def test_only_browser_push_services_are_accepted(url, ok):
    assert push.endpoint_ok(url) is ok


# ------------------------------------------------------------------ the table

def test_devices_save_move_remove_and_cap(db):
    push_db.save("7", FCM, "k" * 30, "a" * 10, "Chrome")
    push_db.save("7", FCM, "n" * 30, "b" * 10)                       # same device: keys refreshed, not duplicated
    assert push_db.count("7") == 1 and push_db.devices("7")[0].p256dh == "n" * 30
    push_db.save("8", FCM, "n" * 30, "b" * 10)                       # someone else signs in on that browser
    assert push_db.count("7") == 0 and push_db.has("8", FCM)
    assert push_db.remove("7", FCM) is False and push_db.remove("8", FCM) is True
    for i in range(push_db.MAX_PER_USER + 3):
        push_db.save("9", f"{FCM}{i}", "k" * 30, "a" * 10)
    assert push_db.count("9") == push_db.MAX_PER_USER


# ------------------------------------------------------------------ sending

def test_send_encrypts_and_signs_for_each_device(db, on, monkeypatch):
    phone, laptop = Browser(FCM), Browser(APPLE)
    for b in (phone, laptop):
        push_db.save("7", b.endpoint, b.p256dh, b64(b.auth))
    svc = PushService(monkeypatch)

    sent = asyncio.run(push.reminder("7", 42, "Call **mom** https://example.com/x"))
    assert sent == 2 and {c.url for c in svc.calls} == {FCM, APPLE}
    for call, browser in ((next(c for c in svc.calls if c.url == b.endpoint), b) for b in (phone, laptop)):
        msg = browser.decrypt(call.data)                            # only the browser's key opens it
        assert msg == {"title": "⏰ Reminder", "body": "Call mom (link on screen)", "url": "/kept", "tag": "reminder-42"}
        assert call.headers["content-encoding"] == "aes128gcm" and call.headers["Urgency"] == "high"
        assert call.headers["ttl"] == str(push.TTL_S)
        # VAPID: a JWT for this push service's origin, signed with our key
        token = call.headers["Authorization"].split("vapid t=")[1].split(",")[0]
        claims = jwt.decode(token, options={"verify_signature": False})
        assert claims["aud"] == "https://" + browser.endpoint.split("/")[2] and claims["sub"] == "mailto:ops@example.com"
        assert call.headers["Authorization"].endswith("k=" + on)
    assert all(d.endpoint for d in push_db.devices("7"))


def test_gone_devices_are_forgotten_and_other_failures_kept(db, on, monkeypatch):
    b = Browser()
    push_db.save("7", b.endpoint, b.p256dh, b64(b.auth))
    PushService(monkeypatch, status=500)
    assert asyncio.run(push.send("7", "t", "b")) == 0 and push_db.count("7") == 1
    PushService(monkeypatch, status=410)
    assert asyncio.run(push.send("7", "t", "b")) == 0 and push_db.count("7") == 0


def test_long_answers_are_shortened_and_off_means_nothing(db, on, monkeypatch):
    b = Browser()
    push_db.save("7", b.endpoint, b.p256dh, b64(b.auth))
    svc = PushService(monkeypatch)
    asyncio.run(push.task_result("7", "Morning brief", "# Today\n" + "word " * 400, conversation_id="c1",
                                 needs_approval=True))
    msg = b.decrypt(svc.calls[0].data)
    assert msg["url"] == "/chat?c=c1" and msg["title"] == "Morning brief"
    assert msg["body"].startswith("Needs your OK") and len(msg["body"]) <= push.MAX_BODY and msg["body"].endswith("…")

    monkeypatch.delenv("VAPID_PRIVATE_KEY")
    assert push.enabled() is False and asyncio.run(push.send("7", "t", "b")) == 0 and len(svc.calls) == 1


# ------------------------------------------------------------------ routes

def client(user="7") -> TestClient:
    app = FastAPI()
    app.include_router(push_route.router)
    app.dependency_overrides[get_current_user] = lambda: {"user_id": user}
    return TestClient(app)


def test_routes(db, on, monkeypatch):
    c, b = client(), Browser()
    sub = {"endpoint": b.endpoint, "keys": {"p256dh": b.p256dh, "auth": b64(b.auth)}}
    assert c.get("/push").json() == {"enabled": True, "public_key": on, "devices": 0, "this_device": False}
    assert c.post("/push/subscribe", json={**sub, "endpoint": "https://10.0.0.5/push"}).status_code == 422
    assert c.post("/push/subscribe", json=sub).json() == {"subscribed": True}
    assert c.get("/push", params={"endpoint": b.endpoint}).json()["this_device"] is True
    PushService(monkeypatch)
    assert c.post("/push/test").json() == {"sent": 1}
    assert client("8").post("/push/unsubscribe", json={"endpoint": b.endpoint}).json() == {"unsubscribed": False}
    assert c.post("/push/unsubscribe", json={"endpoint": b.endpoint}).json() == {"unsubscribed": True}

    monkeypatch.delenv("VAPID_PUBLIC_KEY")
    assert c.get("/push").json()["enabled"] is False
    assert c.post("/push/subscribe", json=sub).status_code == 503


# ------------------------------------------------------------------ the scheduler

def test_due_reminders_go_to_devices_and_whatsapp_only_on_paid_plans(monkeypatch):
    from harness import notify, scheduler
    from harness.db import personal
    from harness.db import whatsapp as wa_db
    from harness.whatsapp import client as wa_client
    from harness.whatsapp import service

    r = SimpleNamespace(id=5, text="Pay rent", due_at=None)
    monkeypatch.setattr(personal, "due_reminders", lambda: [(7, r)])
    monkeypatch.setattr(personal, "claim_due", lambda rid: True)
    monkeypatch.setattr(notify, "email_enabled", lambda: False)
    pushed = []

    async def fake_push(uid, rid, text):
        pushed.append((uid, rid, text))
        return 1
    monkeypatch.setattr(push, "reminder", fake_push)

    monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "t")
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "1")
    link = wa_db.Link(user_id="7", phone="919876543210", linked=True, conversation_id=None,
                      last_inbound_at=None, pending_text=None)
    monkeypatch.setattr(wa_db, "by_user", lambda uid: link)
    sent = []

    async def template(*args):
        sent.append(args)
    monkeypatch.setattr(wa_client, "send_template", template)

    async def charge(uid, n):
        pass
    monkeypatch.setattr(service, "_charge", charge)

    monkeypatch.setattr(service, "_chat_allowed", lambda uid: False)          # Free
    assert asyncio.run(scheduler.fire_reminders()) == 1
    assert pushed == [("7", 5, "Pay rent")] and sent == []

    monkeypatch.setattr(service, "_chat_allowed", lambda uid: True)           # Plus / Pro
    asyncio.run(scheduler.fire_reminders())
    assert len(pushed) == 2 and sent and sent[0][1] == "reminder"
