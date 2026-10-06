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


def _md_html(md: str) -> str:
    """Just enough Markdown for an email body: headings, bullets, bold, links, paragraphs."""
    import re
    out, in_list = [], False
    for line in md.splitlines():
        s = escape(line.strip())
        s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
        s = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2">\1</a>', s)
        if re.match(r"^[-*•]\s+", s):
            if not in_list:
                out.append("<ul style=\"margin:4px 0 8px;padding-left:20px\">")
                in_list = True
            out.append(f"<li>{re.sub(r'^[-*•]\s+', '', s)}</li>")
            continue
        if in_list:
            out.append("</ul>")
            in_list = False
        if m := re.match(r"^#{1,6}\s+(.*)", s):
            out.append(f"<p style=\"font-weight:600;margin:14px 0 4px\">{m.group(1)}</p>")
        elif s:
            out.append(f"<p style=\"margin:0 0 8px\">{s}</p>")
    if in_list:
        out.append("</ul>")
    return "".join(out)


def _approval_html(approval: dict) -> str:
    """The approval card as email HTML: the facts, the text, and Approve / Reject
    buttons that open the /approve/<link> page (which decides on a second, real click)."""
    c, link = approval["card"], approval["url"]
    rows = "".join(f"<tr><td style=\"color:#7A7266;padding:2px 12px 2px 0;vertical-align:top\">{escape(k)}</td>"
                   f"<td style=\"padding:2px 0\">{escape(v)}</td></tr>" for k, v in c.get("rows", []))
    body = (f"<div style=\"white-space:pre-wrap;border-left:3px solid #E5DED3;padding:6px 10px;margin:8px 0;"
            f"color:#2A2620\">{escape(c['body'][:1500])}</div>") if c.get("body") else ""
    button = ("display:inline-block;padding:10px 18px;border-radius:8px;text-decoration:none;font-weight:600;"
              "margin-right:8px")
    return (f"<div style=\"border:1px solid #E5DED3;border-radius:12px;padding:14px 16px;margin:14px 0\">"
            f"<p style=\"font-weight:600;margin:0 0 8px\">{escape(c['title'])}</p>"
            f"<table style=\"border-collapse:collapse;font-size:14px\">{rows}</table>{body}"
            f"<p style=\"margin:14px 0 4px\">"
            f"<a href=\"{escape(link)}?d=approve\" style=\"{button}background:#A8402C;color:#fff\">Approve</a>"
            f"<a href=\"{escape(link)}?d=reject\" style=\"{button}border:1px solid #CFC6B8;color:#2A2620\">Reject</a></p>"
            f"<p style=\"color:#7A7266;font-size:12px;margin:8px 0 0\">You'll see it once more before anything "
            f"happens. The link works once and expires in 24 hours.</p></div>")


def task_email(title: str, answer: str, *, needs_approval: bool = False,
               approval: dict | None = None) -> tuple[str, str, str]:
    """A scheduled task's result. ``approval`` ({card, url}) adds the action waiting for
    the user with Approve / Reject buttons, so they can decide from their inbox."""
    s = get_settings()
    if approval:
        c = approval["card"]
        facts = "\n".join(f"  {k}: {v}" for k, v in c.get("rows", []))
        note = (f"\n\n{c['title']}\n{facts}" + (f"\n\n{c['body'][:1500]}" if c.get("body") else "")
                + f"\n\nApprove or reject (no sign-in needed): {approval['url']}")
    else:
        note = "\n\nOne step needs your approval — open Hangul to continue." if needs_approval else ""
    plain = f"{answer}{note}\n\nOpen Hangul: {s.app_url}"
    html = (f"<div style=\"font-family:system-ui,sans-serif;font-size:15px;line-height:1.55;color:#2A2620;max-width:640px\">"
            f"<p style=\"font-size:18px;margin:0 0 12px\">⏰ {escape(title)}</p>{_md_html(answer)}"
            + (_approval_html(approval) if approval else
               "<p style=\"color:#9A6B1E\">One step needs your approval — open Hangul to continue.</p>" if needs_approval
               else "")
            + f"<p style=\"margin-top:18px\"><a href=\"{escape(s.app_url)}\" style=\"color:#2A2620\">Open Hangul</a></p></div>")
    subject = f"⏰ {title} — needs your OK" if (approval or needs_approval) else f"⏰ {title}"
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
