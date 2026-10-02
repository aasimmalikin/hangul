"""Outgoing notifications: reminder emails via Resend.

Resend is the account the web app already uses for sign-in links, so the
same key works (``resend_api_key`` / ``AUTH_RESEND_KEY``). The key is read
here, by the scheduler -- never by a tool -- and the only recipient is the
user's own sign-in email, so a reminder can never be pointed at a stranger.
"""

from html import escape

import httpx
from sqlalchemy import select

from harness.config import get_settings
from harness.logging import log

RESEND_URL = "https://api.resend.com/emails"


def email_enabled() -> bool:
    s = get_settings()
    return bool(s.resend_api_key and s.email_from)


def user_email(user_id: int | str) -> str | None:
    from harness.db.base import SessionLocal
    from harness.db.models import User
    with SessionLocal() as s:
        return s.execute(select(User.email).where(User.id == int(user_id))).scalar()


def reminder_email(text: str, local_time: str) -> tuple[str, str, str]:
    s = get_settings()
    subject = f"⏰ Reminder: {text[:80]}"
    plain = f"{text}\n\nScheduled for {local_time}.\n\nOpen Hangul: {s.app_url}"
    html = (f"<div style=\"font-family:system-ui,sans-serif;font-size:15px;line-height:1.5\">"
            f"<p style=\"font-size:18px;margin:0 0 8px\">⏰ {escape(text)}</p>"
            f"<p style=\"color:#6E6A62;margin:0 0 16px\">Scheduled for {escape(local_time)}</p>"
            f"<a href=\"{escape(s.app_url)}\" style=\"color:#2A2620\">Open Hangul</a></div>")
    return subject, plain, html


async def send_email(to: str, subject: str, text: str, html: str | None = None) -> bool:
    s = get_settings()
    if not email_enabled():
        return False
    body = {"from": s.email_from, "to": [to], "subject": subject, "text": text}
    if html:
        body["html"] = html
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(RESEND_URL, json=body, headers={"Authorization": f"Bearer {s.resend_api_key}"})
        if r.status_code >= 300:
            log.warning("reminder email rejected", status=r.status_code, body=r.text[:200])
            return False
        return True
    except httpx.HTTPError as e:
        log.warning("reminder email failed", error=str(e))
        return False
