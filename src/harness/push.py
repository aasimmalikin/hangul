"""Web Push: notifications on the user's phone or computer, from the installed
app or the browser, even when Hangul is closed. Free on every plan.

The browser subscribes through its own push service (Google's FCM for Chrome
and Android, Apple for Safari and iPhone, Mozilla, Microsoft) and gives us an
``endpoint`` plus two keys. To notify, we encrypt the message with those keys
(the push service can't read it), sign the request with our VAPID key, and
POST it to the endpoint. A 404/410 means the device is gone, so it is forgotten.

Off until VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY are set
(``python -m harness.push keys`` prints a pair).
"""

import asyncio
import base64
import json
from functools import lru_cache
from urllib.parse import urlsplit

from harness.config import get_settings
from harness.db import push as db
from harness.logging import log

# Only the browsers' push services: an endpoint is a URL the server will POST
# to, so anything else (an internal address) is refused at subscribe time.
PUSH_HOSTS = ("fcm.googleapis.com", "android.googleapis.com", "push.services.mozilla.com",
              "push.apple.com", "notify.windows.com")
TTL_S = 24 * 60 * 60          # a phone that's off for a day still gets it when it comes back
MAX_BODY = 300                # a notification shows a few lines; the rest is in the app


def enabled() -> bool:
    s = get_settings()
    return bool(s.vapid_public_key and s.vapid_private_key)


def public_key() -> str | None:
    return get_settings().vapid_public_key if enabled() else None


def endpoint_ok(endpoint: str) -> bool:
    try:
        u = urlsplit(endpoint)
    except ValueError:
        return False
    host = (u.hostname or "").lower()
    return (u.scheme == "https" and len(endpoint) <= 1024 and not u.port
            and any(host == h or host.endswith("." + h) for h in PUSH_HOSTS))


@lru_cache(maxsize=1)
def _vapid(private_key: str):
    from py_vapid import Vapid
    return Vapid.from_string(private_key=private_key)


def _subject() -> str:
    s = get_settings()
    if s.vapid_subject:
        return s.vapid_subject
    if s.email_from:
        addr = s.email_from.split("<")[-1].rstrip(">").strip()
        return f"mailto:{addr}"
    return s.app_url


def _short(text: str) -> str:
    from harness.media.voice import speech_text  # markdown, code and URLs out
    flat = speech_text(text) or text.strip()
    return flat if len(flat) <= MAX_BODY else flat[: MAX_BODY - 1].rstrip() + "…"


def _send_one(device: db.Device, payload: str, urgency: str) -> bool:
    from pywebpush import WebPushException, webpush
    try:
        webpush(device.info(), data=payload, vapid_private_key=_vapid(get_settings().vapid_private_key),
                vapid_claims={"sub": _subject()},     # fresh dict: webpush fills in aud/exp per endpoint
                ttl=TTL_S, timeout=10, headers={"Urgency": urgency})
    except WebPushException as e:
        status = getattr(e.response, "status_code", None)
        if status in (404, 410):
            db.forget(device.endpoint)
            log.info("push device gone", status=status)
        else:
            log.warning("push failed", status=status, error=str(e)[:200])
        return False
    except Exception as e:  # noqa: BLE001 - one device must not stop the others
        log.warning("push failed", error=f"{type(e).__name__}: {e}"[:200])
        return False
    db.mark_sent(device.endpoint)
    return True


async def send(user_id: str, title: str, body: str, *, url: str = "/", tag: str | None = None,
               urgency: str = "normal") -> int:
    """Notify every device the user turned notifications on for. Returns how many
    got it; 0 when push is off or the user has no devices. Never raises."""
    if not enabled():
        return 0
    try:
        devices = await asyncio.to_thread(db.devices, str(user_id))
    except Exception as e:  # noqa: BLE001
        log.warning("push devices lookup failed", user_id=user_id, error=str(e)[:200])
        return 0
    if not devices:
        return 0
    payload = json.dumps({"title": title[:120], "body": _short(body), "url": url, "tag": tag})
    results = await asyncio.gather(*(asyncio.to_thread(_send_one, d, payload, urgency) for d in devices))
    return sum(results)


async def reminder(user_id: str, reminder_id: int, text: str) -> int:
    # the same tag as the open app's own notification, so the two never show twice
    return await send(user_id, "⏰ Reminder", text, url="/kept", tag=f"reminder-{reminder_id}", urgency="high")


async def task_result(user_id: str, title: str, answer: str, *, conversation_id: str | None,
                      needs_approval: bool = False, url: str | None = None, pending: dict | None = None) -> int:
    """A scheduled task's result. Waiting on the user: the body is the action itself and
    ``url`` (its approval link) opens the Approve / Reject page instead of the chat."""
    if needs_approval and pending:
        from harness.approval_card import one_line
        body = one_line(pending) + " Tap to approve or reject."
    else:
        body = ("Needs your OK before I go on. " if needs_approval else "") + answer
    url = url or (f"/chat?c={conversation_id}" if conversation_id else "/chat")
    return await send(user_id, title or "Hangul", body, url=url, tag=f"task-{conversation_id or title}")


def make_keys() -> tuple[str, str]:
    """A fresh VAPID pair as (public, private), both base64url without padding."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    key = ec.generate_private_key(ec.SECP256R1())
    raw_pub = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    raw_priv = key.private_numbers().private_value.to_bytes(32, "big")
    b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()
    return b64(raw_pub), b64(raw_priv)


if __name__ == "__main__":
    import sys
    if sys.argv[1:] != ["keys"]:
        sys.exit("usage: python -m harness.push keys")
    pub, priv = make_keys()
    print(f"VAPID_PUBLIC_KEY={pub}\nVAPID_PRIVATE_KEY={priv}")
