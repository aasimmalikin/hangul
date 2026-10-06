"""Runs scheduled tasks and fires reminders: every POLL_S, pick tasks whose
next_run_at has passed and run each through the same path as /ask (per-user
tools, connectors, security, cost ledger, episode in the Chats rail), then
deliver due reminders (in-app via status "sent", a push notification, an email,
and WhatsApp on Plus and Pro)."""

import asyncio
import contextlib
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException

from harness.logging import log

POLL_S = 60
APPROVAL_TTL_S = 24 * 3600   # how long a scheduled run's action can wait for the user


def _weekly_only(user_id: str) -> bool:
    """A plan that allows tasks only weekly (Free) slows a daily task down
    rather than stopping it, so a user who downgrades keeps a weekly brief."""
    from harness.billing import entitlements
    from harness.billing.plans import WEEK_MINUTES, get_plan
    from harness.db import billing as billing_db
    if not entitlements.billing_enabled():
        return False
    try:
        return get_plan(billing_db.get_account(user_id).plan).task_min_minutes >= WEEK_MINUTES
    except Exception:  # noqa: BLE001 - a DB blip keeps the stored schedule
        return False


async def run_task(task, *, tz: str) -> None:
    from harness.api.concurrency import run_slot
    from harness.api.routes.ask import AskRequest, _build_and_run
    from harness.db import tasks as tasks_db
    from harness.db.episodes import store_episode

    user_id = str(task.user_id)
    if task.last_status == "needs_approval" and task.last_run_id:
        # the previous run's action is superseded by this one: never approvable later
        await asyncio.to_thread(_store().expire_run, task.last_run_id, user_id)
    tasks_db.mark_started(task.id, tz, weekly=_weekly_only(user_id))
    try:
        # connectors_auto: like a chat message, a task gets the connected apps its question
        # needs ("create an event" -> Calendar) on top of any ticked, or it runs with none
        req = AskRequest(question=task.question, connectors=list(task.connectors), mode=task.mode,
                         connectors_auto=True)
        async with run_slot(user_id):
            # unattended: nobody is watching, so no questions mid-run (see UNATTENDED_INSTRUCTION)
            outcome = await _build_and_run(req, user_id, unattended=True)
        r = outcome.result
        waiting = bool(r.pending_tool)
        status = "needs_approval" if waiting else "done"
        tasks_db.mark_finished(task.id, status=status, run_id=outcome.run.run_id, answer=r.answer)
        # A run that waits for the user always says so, "send me the result" or not:
        # they set it up to run while they were away, so they are not in the chat.
        from harness import push
        from harness.whatsapp.service import notify as whatsapp_notify
        if waiting:
            # The action waits for the user, who set this up to run while away: the approval
            # goes to WhatsApp on Plus and Pro (notify is False on Free or when it isn't
            # linked), otherwise by email with a signed Approve / Reject link
            # (harness.approval_links); a phone notification opens the same page.
            approval, link_path = None, None
            if r.pending_tool.get("name") != "ask_user":
                from harness import approval_links
                from harness.approval_card import card
                token = approval_links.make(outcome.run.run_id, user_id, ttl_s=APPROVAL_TTL_S)
                approval = {"card": card(r.pending_tool), "url": approval_links.url(token)}
                link_path = f"/approve/{token}"
            on_whatsapp = await whatsapp_notify(user_id, "task", r.answer, title=task.title,
                                                pending=r.pending_tool, run_id=outcome.run.run_id)
            if not on_whatsapp:
                await email_result(task, r.answer, needs_approval=True, approval=approval)
            await push.task_result(user_id, task.title, r.answer, conversation_id=outcome.conversation_id,
                                   needs_approval=True, url=link_path, pending=r.pending_tool)
        elif r.answer and task.deliver_email:
            # "send me the result": email, devices, and WhatsApp on Plus and Pro
            await email_result(task, r.answer)
            await push.task_result(user_id, task.title, r.answer, conversation_id=outcome.conversation_id)
            await whatsapp_notify(user_id, "task", r.answer, title=task.title)
        with contextlib.suppress(Exception):
            # the result shows up in the Chats rail like any conversation
            await store_episode(user_id, outcome.run.run_id, r.answer[:1500], title=f"⏰ {task.title}")
        log.info("scheduled task ran", task=task.id, user_id=user_id, status=status)
    except HTTPException as e:
        # plan refusal (402) or a bad stored setting: a state the user must fix
        status = "needs_plan" if e.status_code == 402 else "failed"
        detail = e.detail.get("detail") if isinstance(e.detail, dict) else e.detail
        tasks_db.mark_finished(task.id, status=status, run_id=None, answer=str(detail))
        log.info("scheduled task refused", task=task.id, status=status)
    except Exception as e:  # noqa: BLE001 - one bad task must not stop the scheduler
        tasks_db.mark_finished(task.id, status="failed", run_id=None, answer=f"{type(e).__name__}: {e}")
        log.warning("scheduled task failed", task=task.id, error=str(e))


async def email_result(task, answer: str, *, needs_approval: bool = False, approval: dict | None = None) -> bool:
    """Send a scheduled task's answer (e.g. the morning brief) to the user's own
    address. Failures are logged; the result is still in the Chats rail."""
    from harness import notify
    if not notify.email_enabled():
        return False
    try:
        to = await asyncio.to_thread(notify.user_email, task.user_id)
        if not to:
            return False
        subject, text, html = notify.task_email(task.title, answer, needs_approval=needs_approval, approval=approval)
        return await notify.send_email(to, subject, text, html)
    except Exception as e:  # noqa: BLE001
        log.warning("task email failed", task=task.id, error=str(e))
        return False


async def fire_reminders() -> int:
    """Deliver every due reminder once: mark it sent (the app's bell shows it),
    notify the user's devices, WhatsApp on Plus and Pro, and email it to the
    user's own address when email is configured."""
    from zoneinfo import ZoneInfo

    from harness import notify, push
    from harness.db import personal
    from harness.db.settings import get_settings as user_settings

    due = await asyncio.to_thread(personal.due_reminders)
    fired = 0
    for user_id, r in due:
        if not await asyncio.to_thread(personal.claim_due, r.id):
            continue                       # another worker delivered it
        fired += 1                         # now "sent": the app's bell shows it
        await push.reminder(str(user_id), r.id, r.text)              # no-op without devices
        from harness.whatsapp.service import notify as whatsapp_notify
        await whatsapp_notify(str(user_id), "reminder", r.text)      # no-op unless linked and on Plus/Pro
        if not notify.email_enabled():
            continue
        try:
            to = await asyncio.to_thread(notify.user_email, user_id)
            tz = (await asyncio.to_thread(user_settings, str(user_id))).timezone or "UTC"
            local = r.due_at.astimezone(ZoneInfo(tz)).strftime("%a %d %b, %H:%M")
            if to and await notify.send_email(to, *notify.reminder_email(r.text, local)):
                await asyncio.to_thread(personal.mark_emailed, r.id)
        except Exception as e:  # noqa: BLE001 - the in-app reminder already went out
            log.warning("reminder email step failed", reminder=r.id, error=str(e))
    if fired:
        log.info("reminders fired", count=fired)
    return fired


def _store():
    from harness.api.routes.ask import _store as store
    return store


async def expire_stale_approvals(now: datetime | None = None) -> int:
    """A task run's action that has waited APPROVAL_TTL_S is closed: approving
    Monday's "4pm meeting" on Thursday would do the wrong thing."""
    from harness.db import tasks as tasks_db
    before = (now or datetime.now(UTC)) - timedelta(seconds=APPROVAL_TTL_S)
    n = 0
    for task_id, user_id, run_id in await asyncio.to_thread(tasks_db.waiting_since, before):
        expired = await asyncio.to_thread(_store().expire_run, run_id, str(user_id))
        # not waiting any more either way: expired now, or the user already decided
        await asyncio.to_thread(tasks_db.set_status, task_id, "expired" if expired else "done")
        n += expired
    if n:
        log.info("stale task approvals expired", count=n)
    return n


async def tick() -> int:
    from harness.db import tasks as tasks_db
    from harness.db.settings import get_settings as user_settings

    await expire_stale_approvals()

    due = await asyncio.to_thread(tasks_db.due_tasks)
    for task in due:
        tz = (await asyncio.to_thread(user_settings, str(task.user_id))).timezone
        await run_task(task, tz=tz)
    return len(due)


async def loop() -> None:
    while True:
        try:
            await tick()
        except Exception as e:  # noqa: BLE001
            log.warning("scheduler tick failed", error=str(e))
        try:
            await fire_reminders()
        except Exception as e:  # noqa: BLE001
            log.warning("reminder tick failed", error=str(e))
        await asyncio.sleep(POLL_S)


def start() -> asyncio.Task:
    return asyncio.create_task(loop(), name="scheduler")
