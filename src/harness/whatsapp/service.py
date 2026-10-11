"""What happens to a WhatsApp message, and how notifications reach WhatsApp.

Inbound: dedupe by message id -> "typing…" -> linking code? -> linked number?
-> the plan (WhatsApp is Plus) -> the message becomes a question
(text, a transcribed voice note, or a photo/document indexed like an upload)
-> the same agent run as the app (``_build_and_run``: tools, approvals,
memory, billing, security) in the user's WhatsApp conversation -> the answer,
formatted and split, or Approve / Reject buttons, or the agent's choices.

Outbound (Plus and Pro, like chatting; Free gets app notifications and email):
reminders and task results (the morning brief) go to a linked
number as plain text inside the 24-hour window, else as approved templates;
a brief that had to use the template waits in ``pending_text`` and is sent
when the user next writes.

Each message Hangul sends is charged at ``whatsapp_usd_per_message``.
"""

import asyncio
import json
import re
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import HTTPException

from harness.config import get_settings
from harness.db import whatsapp as db
from harness.logging import log
from harness.whatsapp import client, enabled
from harness.whatsapp.fmt import one_line, split, to_whatsapp
from harness.whatsapp.inbound import Inbound

LINK_RE = re.compile(r"\bhangul\s+(\d{6})\b", re.I)
SHOW_PENDING = {"brief", "show", "show me", "yes", "ok", "okay", "send", "read"}
MIME_EXT = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "application/pdf": ".pdf",
            "text/plain": ".txt", "text/csv": ".csv",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx"}

# short labels for the approval message
ACTION_LABEL = {
    "gmail__send_message": "Send this email", "gmail__send_draft": "Send this draft", "gmail__create_draft": "Save this draft",
    "calendar__create_event": "Add this to your calendar", "calendar__update_event": "Change this event",
    "calendar__delete_event": "Delete this event", "sheets__append_rows": "Add rows to this sheet",
    "slack__send_message": "Post this to Slack", "github__create_issue": "Open this GitHub issue",
    "github__comment": "Post this GitHub comment", "web_search": "Search the web", "read_webpage": "Open this page",
}


def _app(path: str) -> str:
    return get_settings().app_url.rstrip("/") + path


async def _charge(user_id: str, messages: int) -> None:
    if messages <= 0:
        return
    from harness.billing import entitlements
    usd = Decimal(str(get_settings().whatsapp_usd_per_message)) * messages
    try:
        await asyncio.to_thread(entitlements.settle, user_id, usd, None)
    except Exception as e:  # noqa: BLE001 - a ledger blip must not lose the message
        log.warning("whatsapp charge failed", user_id=user_id, error=str(e)[:200])


async def say(phone: str, text: str, user_id: str | None = None, *, markdown: bool = True) -> int:
    """Send text, split when long. ``markdown``: an agent answer, converted to
    WhatsApp formatting; False for Hangul's own messages, already written that way."""
    sent = 0
    for chunk in split((to_whatsapp(text) if markdown else text.strip()) or "…"):
        await client.send_text(phone, chunk)
        sent += 1
    if user_id:
        await _charge(user_id, sent)
    return sent


def describe_action(pending: dict) -> str:
    """The approval message: what Hangul wants to do, with the details that matter."""
    name, a = pending.get("name", ""), pending.get("arguments") or {}
    label = ACTION_LABEL.get(name, f"Run {name.replace('__', ' ').replace('_', ' ')}")
    if name.startswith("gmail__") and ("to" in a or "subject" in a):
        body = (a.get("body") or "")[:600]
        return f"*{label}?*\nTo: {a.get('to', '')}\nSubject: {a.get('subject', '')}\n\n{body}".strip()
    if name.startswith("calendar__"):
        when = " → ".join(x for x in (a.get("start"), a.get("end")) if x)
        return f"*{label}?*\n{a.get('summary', '')}\n{when}".strip()
    if name in ("web_search", "read_webpage"):
        return f"*{label}?*\n{a.get('query') or a.get('url') or ''}"
    detail = json.dumps(a, ensure_ascii=False)[:600]
    return f"*{label}?*\n{detail}"


async def deliver(phone: str, user_id: str, run_id: str, answer: str, pending: dict | None) -> None:
    """A finished (or paused) run, as WhatsApp messages."""
    sent = 0
    if pending and pending.get("name") == "ask_user":
        a = pending.get("arguments") or {}
        options = [o.get("label", str(o)) if isinstance(o, dict) else str(o) for o in a.get("options") or []]
        question = a.get("question") or "Which one?"
        if 0 < len(options) <= 3:
            await client.send_buttons(phone, question, [(f"pick:{run_id}:{i}", o) for i, o in enumerate(options)])
        else:
            descs = [o.get("description", "") if isinstance(o, dict) else "" for o in a.get("options") or []]
            await client.send_list(phone, question, "Choose", [(f"pick:{run_id}:{i}", o, descs[i]) for i, o in enumerate(options)])
        sent = 1
    elif pending:
        await client.send_buttons(phone, describe_action(pending), [(f"ok:{run_id}", "Approve"), (f"no:{run_id}", "Reject")])
        sent = 1
    else:
        sent = await say(phone, answer)
    await _charge(user_id, sent)


# What WhatsApp does on the Free plan: the shop basics, so the main channel has a free way in.
# All SAFE and no ask_user, so a run doesn't pause: /approve would resume with the plan's normal tools.
FREE_TOOLS = frozenset({"business", "reminders", "lists", "notes", "promises", "customers", "remember"})


def _chat_allowed(user_id: str) -> bool:
    """Full WhatsApp -- every tool, the brief, task results -- is Plus and Pro. Free users
    get the shop basics (FREE_TOOLS) and their reminders here while the 24-hour window is
    open (free to send); outside it, reminders come as app notifications and email."""
    from harness.billing import entitlements
    from harness.billing.plans import get_plan
    from harness.db import billing as billing_db
    if not entitlements.billing_enabled():
        return True
    return get_plan(billing_db.get_account(user_id).plan).id != "free"


async def _question(msg: Inbound, user_id: str) -> str | None:
    """What the user asked: their text, a transcribed voice note, or a file they sent (indexed)."""
    if msg.kind == "text":
        return msg.text.strip() or None
    if msg.kind == "unsupported":
        await say(msg.phone, "I can read text, voice notes, photos and documents (PDF, Word, Excel, CSV).", user_id, markdown=False)
        return None
    data, mime = await client.download_media(msg.media_id or "")
    if msg.kind == "audio":
        from harness.media.voice import transcribe
        text = await transcribe(data, "voice.ogg", user_id=user_id)
        return text.strip() or None
    # a photo or document: saved and indexed exactly like an upload in the app
    import io

    from starlette.datastructures import UploadFile

    from harness.api.routes.upload import upload
    ext = MIME_EXT.get((mime or "").split(";")[0].strip(), "")
    name = msg.filename or f"whatsapp-{msg.wamid[-8:]}{ext}"
    try:
        await upload(UploadFile(file=io.BytesIO(data), filename=name), user={"user_id": user_id})
    except HTTPException as e:
        await say(msg.phone, f"I couldn't use that file: {e.detail if isinstance(e.detail, str) else 'unsupported type'}.", user_id, markdown=False)
        return None
    caption = msg.text.strip()
    if caption:
        return caption + f" (about the file I just sent: {name})"
    return (f"I just sent {name}. If it's a bill book page or a day-end sales report, log it as my sales; "
            "otherwise tell me briefly what it is.")


async def _run(msg: Inbound, link: db.Link, question: str, *, basics: bool = False) -> None:
    """basics: the Free plan's shop basics only (FREE_TOOLS, no apps)."""
    from harness.api.concurrency import run_slot
    from harness.api.routes.ask import AskRequest, _build_and_run
    uid = link.user_id
    req = AskRequest(question=question[:4000], conversation_id=link.conversation_id, model="auto",
                     connectors_auto=not basics)
    only = FREE_TOOLS if basics else None
    try:
        try:
            async with run_slot(uid):
                outcome = await _build_and_run(req, uid, only_tools=only)
        except HTTPException as e:
            if e.status_code == 404 and req.conversation_id:          # the chat was deleted: start a new one
                req = req.model_copy(update={"conversation_id": None})
                async with run_slot(uid):
                    outcome = await _build_and_run(req, uid, only_tools=only)
            else:
                raise
    except HTTPException as e:
        detail = e.detail.get("detail") if isinstance(e.detail, dict) else str(e.detail)
        if e.status_code == 409:
            text = "I'm still working on your last message. One moment."
        elif e.status_code == 402:
            text = f"{detail} Plans: {_app('/billing')}"
        elif e.status_code == 429:
            text = "That's a lot at once. Give me a minute and try again."
        else:
            text = f"Sorry, I couldn't do that ({detail})."
        await say(msg.phone, text, uid, markdown=False)
        return
    if outcome.conversation_id and outcome.conversation_id != link.conversation_id:
        await asyncio.to_thread(db.update, uid, conversation_id=outcome.conversation_id)
    r = outcome.result
    await deliver(msg.phone, uid, outcome.run.run_id, r.answer, r.pending_tool)


async def _choice(msg: Inbound, link: db.Link) -> None:
    """A tapped Approve / Reject / option button: resume the paused run, as /approve does."""
    from harness.api.routes.approve import ApproveRequest, _store, approve
    kind, _, rest = (msg.reply_id or "").partition(":")
    if kind == "mis":                                     # a mission's go-ahead (harness.missions)
        from harness.missions import slow_day
        reply, buttons = await slow_day.on_button(link.user_id, rest)
        if buttons:
            await client.send_buttons(msg.phone, reply, buttons)
            await _charge(link.user_id, 1)
        else:
            await say(msg.phone, reply, link.user_id, markdown=False)
        return
    run_id, _, index = rest.partition(":")
    if kind not in ("ok", "no", "pick") or not run_id:
        # a template's quick reply or an unknown button: treat its text as a message
        if msg.text:
            await _run(msg, link, msg.text, basics=not await asyncio.to_thread(_chat_allowed, link.user_id))
        return
    choice = None
    if kind == "pick":
        cp = await asyncio.to_thread(_store.load, run_id)
        opts = ((cp.pending_tool or {}).get("arguments") or {}).get("options") or [] if cp else []
        i = int(index) if index.isdigit() else -1
        choice = (opts[i].get("label") if isinstance(opts[i], dict) else str(opts[i])) if 0 <= i < len(opts) else msg.text
    decision = "reject" if kind == "no" else "approve"
    try:
        resp = await approve(ApproveRequest(approval_id=run_id, decision=decision, choice=choice),
                             user={"user_id": link.user_id})
    except HTTPException as e:
        detail = e.detail.get("detail") if isinstance(e.detail, dict) else str(e.detail)
        await say(msg.phone, "That was already handled." if e.status_code == 404 else detail, link.user_id, markdown=False)
        return
    await deliver(msg.phone, link.user_id, resp.run_id, resp.answer, resp.pending_tool)


async def handle(msg: Inbound) -> None:
    """One inbound message. Never raises: failures are logged and, where possible, told to the user."""
    try:
        if not await asyncio.to_thread(db.first_time, msg.wamid):
            return                                        # a retried delivery
        await client.mark_read(msg.wamid)
        link = await asyncio.to_thread(db.by_phone, msg.phone)

        code = LINK_RE.search(msg.text or "") if msg.kind == "text" else None
        if code:
            uid = await asyncio.to_thread(db.claim_code, code.group(1), msg.phone)
            if uid:
                await client.send_text(msg.phone, "✅ WhatsApp is linked to your Hangul account. Ask me anything here, "
                                                  "and your reminders will arrive here too.")
                await _charge(uid, 1)
                return
            if link is None:
                await client.send_text(msg.phone, "That code didn't work or has expired. Get a new one in Hangul: "
                                                  f"{_app('/settings#whatsapp')}")
                return
        if link is None or not link.linked:
            await client.send_text(msg.phone, "Hi! This number isn't linked to a Hangul account yet. Open "
                                              f"{_app('/settings#whatsapp')}, tap *Link WhatsApp* and send the code shown there.")
            return

        uid = link.user_id
        await asyncio.to_thread(db.update, uid, last_inbound_at=datetime.now(UTC))
        waiting = link.pending_text
        if waiting:                                       # a brief that waited for the 24-hour window
            await asyncio.to_thread(db.update, uid, pending_text=None)
            await say(msg.phone, waiting, uid, markdown=False)
            await send_waiting_tasks(msg.phone, uid)       # and the buttons for any task waiting on them
            try:
                from harness.missions.tell import send_waiting
                await send_waiting(msg.phone, uid)         # and any mission waiting for a go-ahead
            except Exception as e:  # noqa: BLE001 - the brief and the message itself still go through
                log.warning("whatsapp: waiting missions skipped", error=str(e)[:200])
            if msg.kind == "text" and msg.text.strip().lower() in SHOW_PENDING:
                return

        if msg.kind == "choice":
            await _choice(msg, link)
            return
        basics = not await asyncio.to_thread(_chat_allowed, uid)     # Free: the shop basics only
        question = await _question(msg, uid)
        if question:
            await _run(msg, link, question, basics=basics)
    except Exception as e:  # noqa: BLE001 - the webhook already answered 200; tell the user, keep going
        log.error("whatsapp message failed", wamid=msg.wamid, error=f"{type(e).__name__}: {e}"[:300])
        try:
            await client.send_text(msg.phone, "Sorry, something went wrong on my side. Please try again.")
        except Exception:  # noqa: BLE001
            pass


async def send_waiting_tasks(phone: str, user_id: str, limit: int = 3) -> int:
    """Approve/Reject buttons for scheduled runs still waiting on this user (their notice
    went out as a template, which can't carry buttons). Expired or decided runs are skipped."""
    from harness.api.routes.approve import _store
    from harness.db import tasks as tasks_db
    sent = 0
    for _title, run_id in (await asyncio.to_thread(tasks_db.waiting_runs, user_id))[:limit]:
        cp = await asyncio.to_thread(_store.load, run_id)
        if cp is not None and cp.status == "pending_approval" and cp.pending_tool:
            await deliver(phone, user_id, run_id, "", cp.pending_tool)
            sent += 1
    return sent


async def notify(user_id: str, kind: str, text: str, *, title: str = "",
                 pending: dict | None = None, run_id: str | None = None) -> bool:
    """A reminder (kind="reminder") or a task result such as the brief (kind="task")
    to the user's linked number. Plain text inside the 24-hour window, otherwise
    the approved template. False when WhatsApp is off or the number isn't linked;
    on Free, True only for a reminder inside the window (free to send) -- otherwise
    they get app notifications and email instead.
    ``pending`` (a task run waiting for the user) adds Approve/Reject buttons: at once
    inside the window, else when they reply to the template (``send_waiting_tasks``)."""
    if not enabled():
        return False
    link = await asyncio.to_thread(db.by_user, str(user_id))
    if link is None or not link.linked or not link.phone:
        return False
    try:
        if not await asyncio.to_thread(_chat_allowed, str(user_id)) and not (kind == "reminder" and link.window_open()):
            return False
    except Exception as e:  # noqa: BLE001 - a DB blip: skip WhatsApp, the other channels still deliver
        log.warning("whatsapp plan check failed", user_id=user_id, error=str(e)[:200])
        return False
    s = get_settings()
    try:
        if link.window_open():
            body = f"⏰ *Reminder:* {text}" if kind == "reminder" else (f"*{title}*\n\n{text}" if title else text)
            await say(link.phone, body, str(user_id), markdown=False)
            if pending and run_id:
                await deliver(link.phone, str(user_id), run_id, "", pending)
        elif kind == "reminder":
            await client.send_template(link.phone, s.whatsapp_template_reminder, [one_line(text)])
            await _charge(str(user_id), 1)
        elif pending and run_id and s.whatsapp_template_approval:
            # the approval card itself, with Approve / Reject, even outside the window
            from harness.approval_card import one_line as action_line
            await client.send_template(link.phone, s.whatsapp_template_approval, [title or "your task", action_line(pending)],
                                       [f"ok:{run_id}", f"no:{run_id}"])
            await _charge(str(user_id), 1)
        else:
            from harness.db.settings import get_settings as user_settings
            name = ((await asyncio.to_thread(user_settings, str(user_id))).display_name or "there").split()[0]
            await client.send_template(link.phone, s.whatsapp_template_brief, [name])
            await asyncio.to_thread(db.update, str(user_id), pending_text=(f"*{title}*\n\n{text}" if title else text))
            await _charge(str(user_id), 1)
        return True
    except Exception as e:  # noqa: BLE001 - email and the in-app bell still deliver it
        log.warning("whatsapp notify failed", user_id=user_id, kind=kind, error=str(e)[:200])
        return False
