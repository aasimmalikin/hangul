"""Kept your word: Hangul notices promises -- the user's and other people's --
and makes sure they're kept.

Where promises come from:
  chat      the ``promises`` tool ("I told Priya I'd send the deck Friday"),
            including the reply to the after-meeting question on WhatsApp
  meeting   the after-meeting question answered on Today (``capture``)
  email     mail the user sent and received, read every ``EMAIL_EVERY`` (Plus)

What Hangul does with them:
  - the morning a promise of the user's is due (or overdue): one nudge
  - a promise owed to the user that's overdue with no word back: one nudge
    offering to chase; chasing drafts a follow-up in chat, and sending it
    waits for the user's tap like every email (Plus)
  - before a meeting, Today's Next up lists what's open with those people
  - when the other side writes back in the same thread (or the user does, for
    their own), the promise shows "wrote back", so it can be marked kept

Plans: Free keeps promises told in chat and gets their due-day nudges; Plus
adds reading email, the after-meeting question and chasing.
"""

import asyncio
import time
from datetime import UTC, date, datetime, timedelta
from email.utils import getaddresses, parseaddr
from zoneinfo import ZoneInfo

from harness.db import promises as db
from harness.logging import log
from harness.promises import extract

EMAIL_EVERY = timedelta(minutes=30)
MEETINGS_EVERY = timedelta(minutes=10)
NUDGES_EVERY_S = 10 * 60
EMAIL_LOOKBACK_D = 2          # newer_than for each read; the first read looks back 1 day
EMAIL_MAX = 15                # messages per folder per read
MEETING_ASK_AFTER = timedelta(minutes=5)    # ask this long after a meeting ends...
MEETING_ASK_UNTIL = timedelta(minutes=45)   # ...and not after this
MEETING_ASKS_DAY = 4
ASK_FRESH = timedelta(hours=12)             # how long an asked meeting can still be answered
DAY_HOURS = (8, 21)                         # local hours Hangul may message the user
THEIRS_UNDATED_AFTER = timedelta(days=4)    # an undated promise owed to the user is "late" after this
MAX_RECIPIENTS = 10

_last_nudges = 0.0


# ------------------------------------------------------------ who may do what

def access(user_id: str) -> dict:
    from harness.billing import entitlements
    from harness.billing.plans import get_plan, plan_allows_tool
    if not entitlements.billing_enabled():
        return {"plan": None, "email": True, "meetings": True, "chase": True}
    from harness.db import billing as billing_db
    plan = get_plan(billing_db.get_account(user_id).plan)
    return {"plan": plan.id, "email": plan_allows_tool(plan, "promises_email"),
            "meetings": plan_allows_tool(plan, "promises_meetings"), "chase": plan_allows_tool(plan, "promises_chase")}


def _can_spend(user_id: str) -> bool:
    from harness.billing import entitlements
    if not entitlements.billing_enabled():
        return True
    try:
        return entitlements.standing(user_id).can_spend
    except Exception:  # noqa: BLE001
        return False


def _tz(user_id: str) -> ZoneInfo:
    from harness.db.settings import get_settings as user_settings
    try:
        return ZoneInfo(user_settings(user_id).timezone or "UTC")
    except Exception:  # noqa: BLE001
        return ZoneInfo("UTC")


def google_users(product: str) -> list[str]:
    """Users whose Google grant includes ``product`` (gmail, calendar)."""
    from sqlalchemy import select

    from harness.db.base import SessionLocal
    from harness.db.models import Account, User
    from harness.integrations.google_oauth import (
        RESTRICTED_PRODUCTS,
        WORKSPACE_SCOPES,
        restricted_allowed,
    )
    need = WORKSPACE_SCOPES[product]
    with SessionLocal() as s:
        rows = s.execute(select(Account.userId, Account.scope, User.email).outerjoin(User, User.id == Account.userId)
                         .where(Account.provider == "google", Account.refresh_token.is_not(None))).all()
    return sorted({str(u) for u, scope, email in rows if all(n in (scope or "").split() for n in need)
                   and (product not in RESTRICTED_PRODUCTS or restricted_allowed(email))})


def name_from_email(addr: str) -> str:
    """'priya.sharma@acme.in' -> 'Priya Sharma' (when there's no display name)."""
    local = (addr or "").split("@")[0]
    parts = [p for p in local.replace("_", ".").replace("-", ".").split(".") if p and not p.isdigit()]
    return " ".join(p.capitalize() for p in parts[:3]) or addr


# ------------------------------------------------------------ email

async def _my_address(user_id: str) -> str:
    from harness.connectors.replies import _my_address
    return (await _my_address(user_id, None)).lower()


def _automated(msg: dict) -> bool:
    from harness.connectors.replies import _automated
    return _automated(msg)


async def _messages(user_id: str, query: str) -> list[dict]:
    from harness.connectors.google_rest import GMAIL, _request
    r = await _request(None, user_id, "gmail", "GET", f"{GMAIL}/messages", params={"q": query, "maxResults": EMAIL_MAX})
    return r.json().get("messages", [])


async def _full(user_id: str, message_id: str) -> dict:
    from harness.connectors.google_rest import GMAIL, _request
    r = await _request(None, user_id, "gmail", "GET", f"{GMAIL}/messages/{message_id}", params={"format": "full"})
    return r.json()


def email_item(msg: dict, me: str, tz: ZoneInfo) -> dict | None:
    """One Gmail message as extraction input, or None when it can't hold a
    promise worth keeping (automated, to a crowd, not to or from the user)."""
    from harness.connectors.google_rest import _body_text, _header
    labels = set(msg.get("labelIds", []))
    if labels & {"SPAM", "TRASH", "CATEGORY_PROMOTIONS", "CATEGORY_SOCIAL", "CATEGORY_UPDATES", "CATEGORY_FORUMS"}:
        return None
    name, sender = parseaddr(_header(msg, "From"))
    sender = sender.lower()
    to = [(n, a.lower()) for n, a in getaddresses([_header(msg, "To")]) if a]
    cc = [a for _, a in getaddresses([_header(msg, "Cc")]) if a]
    if not to or len(to) + len(cc) > MAX_RECIPIENTS:
        return None
    mine = sender == me or "SENT" in labels
    if mine:
        others = [(n, a) for n, a in to if a != me]
        if not others:
            return None                                   # a note to self
        who_name, who_email = others[0]
    else:
        if me not in [a for _, a in to] or _automated(msg):
            return None                                   # only Cc'd, a list, or a machine
        who_name, who_email = name, sender
    text = extract.clean_body(_body_text(msg.get("payload", {})))
    if len(text) < 15:
        return None
    sent = datetime.fromtimestamp(int(msg.get("internalDate", "0")) / 1000, tz=UTC)
    return {"id": msg.get("id"), "thread": msg.get("threadId", ""), "text": text, "day": sent.astimezone(tz).date(),
            "at": sent, "direction": "mine" if mine else "theirs",
            "who": who_name or name_from_email(who_email), "who_email": who_email,
            "writer": "the user" if mine else f"{name or sender} <{sender}>",
            "to": ", ".join(f"{n} <{a}>".strip() for n, a in to)}


def contacts_to_mark(items: list[dict], open_threads: dict) -> list[int]:
    """Promises whose other side has since written in the same thread: the
    promiser wrote again after the promise (they wrote back / you did)."""
    ids = []
    for it in items:
        for pid, direction, created in open_threads.get(it["thread"], []):
            if it["at"] > created and it["direction"] == direction:
                ids.append(pid)
    return ids


async def scan_email(user_id: str, now: datetime | None = None) -> int:
    """Read new mail for promises. Returns how many were added."""
    from harness.billing import meter
    from harness.security import detector
    now = now or datetime.now(UTC)
    state = await asyncio.to_thread(db.scan_state, user_id)
    if not state["email_on"]:
        return 0
    first = state["email_at"] is None
    await asyncio.to_thread(db.save_scan, user_id, email_at=now)
    me = await _my_address(user_id)
    tz = await asyncio.to_thread(_tz, user_id)
    window = "newer_than:1d" if first else f"newer_than:{EMAIL_LOOKBACK_D}d"
    seen = set(state["seen"])
    refs = []
    for q in (f"in:sent {window}", f"in:inbox category:primary {window} -from:me"):
        refs += [m["id"] for m in await _messages(user_id, q) if m["id"] not in seen]
    refs = list(dict.fromkeys(refs))
    if not refs:
        return 0
    gate = asyncio.Semaphore(5)

    async def one(mid: str):
        async with gate:
            try:
                return await _full(user_id, mid)
            except Exception as e:  # noqa: BLE001 - one message failing doesn't stop the read
                log.info("promises: message skipped", error=str(e)[:200])
                return None
    msgs = [m for m in await asyncio.gather(*(one(r) for r in refs)) if m]
    items = [it for it in (email_item(m, me, tz) for m in msgs) if it]
    # a reply in a thread with an open promise: it may already be kept
    open_threads = await asyncio.to_thread(db.seen_threads, user_id)
    await asyncio.to_thread(db.mark_contact, user_id, contacts_to_mark(items, open_threads), now)
    # text that reads like instructions to an assistant never reaches the model
    items = [it for it in items if detector.scan(it["text"]).severity not in ("medium", "high")]
    added = 0
    if items:
        async with meter.metering(user_id, settle_on_exit=True):
            found = await extract.from_emails(items)
        for f in found:
            it = items[f.msg]
            try:
                await asyncio.to_thread(db.add, user_id, it["direction"], f.what, who=it["who"], who_email=it["who_email"],
                                        due_on=f.due, source="email", source_ref=it["id"], thread_ref=it["thread"],
                                        quote=f.quote)
                added += 1
            except db.LimitReached:
                break
    await asyncio.to_thread(db.save_scan, user_id, seen_add=[m.get("id") for m in msgs] + refs)
    if added:
        log.info("promises found in email", user_id=user_id, count=added)
    return added


# ------------------------------------------------------------ meetings

def meetings_to_ask(events: list[dict], me_emails: set[str], asked: list[dict], now: datetime) -> list[dict]:
    """Meetings with other people that ended a few minutes ago and haven't been asked about."""
    done = {a.get("id") for a in asked}
    out = []
    for e in events:
        if e.get("all_day") or not e.get("end") or e.get("id") in done:
            continue
        others = [a.lower() for a in (e.get("attendees") or []) if a and a.lower() not in me_emails]
        if not others:
            continue
        end = datetime.fromisoformat(str(e["end"]).replace("Z", "+00:00"))
        if now - MEETING_ASK_UNTIL <= end <= now - MEETING_ASK_AFTER:
            out.append({"id": e.get("id"), "summary": e.get("summary") or "your meeting",
                        "people": [{"name": name_from_email(a), "email": a} for a in others[:6]]})
    return out


def ask_text(m: dict) -> str:
    names = [p["name"] for p in m["people"]]
    who = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1] if names else "them"
    return (f"How did “{m['summary']}” with {who} go? Was anything promised, by you or by them? "
            "Reply with a quick voice note or a line, and I'll keep track.")


async def _events_just_ended(user_id: str, now: datetime) -> list[dict]:
    from harness.connectors.google_rest import make_google_tools
    tool = next(t for t in make_google_tools(user_id) if t.name == "calendar__list_events")
    out = await tool.handler(time_min=(now - timedelta(hours=3)).isoformat(), time_max=now.isoformat(), max_results=20)
    return [] if isinstance(out, str) else (out.ui or {}).get("events", [])


async def check_meetings(user_id: str, now: datetime | None = None) -> int:
    """Ask about meetings that just ended. Returns how many were asked."""
    from harness import notify
    now = now or datetime.now(UTC)
    state = await asyncio.to_thread(db.scan_state, user_id)
    tz = await asyncio.to_thread(_tz, user_id)
    local = now.astimezone(tz)
    if not DAY_HOURS[0] <= local.hour < DAY_HOURS[1]:
        return 0
    await asyncio.to_thread(db.save_scan, user_id, meetings_at=now)
    today = [a for a in state["asked"] if str(a.get("at", ""))[:10] == local.date().isoformat()]
    if len(today) >= MEETING_ASKS_DAY:
        return 0
    me = {e for e in [await asyncio.to_thread(notify.user_email, user_id)] if e}
    try:
        me.add(await _my_address(user_id))
    except Exception as e:  # noqa: BLE001 - no Gmail scope: the sign-in address is enough
        log.info("promises: no Gmail address for meetings", error=str(e)[:120])
    events = await _events_just_ended(user_id, now)
    asked = 0
    for m in meetings_to_ask(events, {e.lower() for e in me}, state["asked"], now)[:MEETING_ASKS_DAY - len(today)]:
        await asyncio.to_thread(db.save_scan, user_id, asked_add=[{**m, "at": local.isoformat(), "answered": False}])
        await tell(user_id, ask_text(m), url="/#promises", tag=f"meeting-{m['id']}", conversation_note=True)
        asked += 1
    return asked


def recent_asked(asked: list[dict], now: datetime) -> list[dict]:
    """Meetings asked about that can still be answered, newest first."""
    out = []
    for a in reversed(asked or []):
        try:
            at = datetime.fromisoformat(str(a.get("at")))
        except ValueError:
            continue
        if not a.get("answered") and now - at <= ASK_FRESH:
            out.append(a)
    return out


def match_person(who: str, asked: list[dict]) -> str:
    """The email of a person in a recently asked meeting whose name matches ``who``."""
    words = {w.lower() for w in (who or "").split() if len(w) > 1}
    if not words:
        return ""
    for a in asked:
        for p in a.get("people", []):
            if words & {w.lower() for w in p.get("name", "").split()}:
                return p.get("email", "")
    return ""


async def capture(user_id: str, text: str, meeting_id: str | None = None) -> list[db.PromiseOut]:
    """The user's answer to "anything promised?" (Today): find the promises in it."""
    from harness.billing import meter
    now = datetime.now(UTC)
    tz = await asyncio.to_thread(_tz, user_id)
    state = await asyncio.to_thread(db.scan_state, user_id)
    recent = recent_asked(state["asked"], now)
    meeting = next((a for a in recent if a.get("id") == meeting_id), recent[0] if recent else None)
    people = [p["name"] for p in (meeting or {}).get("people", [])]
    async with meter.metering(user_id, settle_on_exit=True):
        found = await extract.from_note(text, now.astimezone(tz).date(), people)
    out = []
    for f in found:
        who, email = f.who, ""
        if f.direction == "theirs" or who:
            email = match_person(who, [meeting] if meeting else [])
        elif meeting and len(meeting["people"]) == 1:              # "I'll send it" in a one-to-one
            who, email = meeting["people"][0]["name"], meeting["people"][0]["email"]
        out.append(await asyncio.to_thread(db.add, user_id, f.direction, f.what, who=who, who_email=email,
                                           due_on=f.due, source="meeting", source_ref=(meeting or {}).get("id") or "",
                                           quote=f.quote))
    if meeting:
        await asyncio.to_thread(answered, user_id, meeting["id"])
    return out


def answered(user_id: str, meeting_id: str) -> None:
    from harness.db.base import SessionLocal
    from harness.db.models import PromiseScan
    with SessionLocal() as s:
        row = s.get(PromiseScan, int(user_id))
        if row is None:
            return
        row.asked = [{**a, "answered": True} if a.get("id") == meeting_id else a for a in (row.asked or [])]
        s.commit()


# ------------------------------------------------------------ telling the user

async def tell(user_id: str, text: str, *, url: str, tag: str, conversation_note: bool = False) -> list[str]:
    """Push (every plan) and WhatsApp (Plus and up, inside Meta's 24-hour window
    only: these aren't worth a template). ``conversation_note`` also puts the
    message into the user's WhatsApp chat, so their reply is read with it."""
    from harness import push
    used = []
    try:
        if await push.send(user_id, "Hangul", text, url=url, tag=tag):
            used.append("push")
    except Exception as e:  # noqa: BLE001
        log.warning("promises push failed", error=str(e)[:200])
    try:
        from harness.db import whatsapp as wa_db
        from harness.whatsapp import enabled
        from harness.whatsapp import service as wa
        if enabled():
            link = await asyncio.to_thread(wa_db.by_user, user_id)
            if (link and link.linked and link.phone and link.window_open()
                    and await asyncio.to_thread(wa._chat_allowed, user_id)):
                await wa.say(link.phone, text, user_id, markdown=False)
                used.append("whatsapp")
                if conversation_note and link.conversation_id:
                    from harness.db import conversations as conv_db
                    await asyncio.to_thread(conv_db.append_messages, link.conversation_id, f"promise-{tag}"[:64],
                                            [{"role": "assistant", "content": text}])
    except Exception as e:  # noqa: BLE001 - push and Today still have it
        log.warning("promises whatsapp failed", user_id=user_id, error=str(e)[:200])
    return used


def late(p, today: date, now: datetime) -> bool:
    """Is a promise owed to the user late with no word back?"""
    if p.direction != "theirs" or p.last_contact_at is not None or p.chased_at is not None:
        return False
    if p.due_on:
        return p.due_on < today
    created = p.created_at if p.created_at.tzinfo else p.created_at.replace(tzinfo=UTC)
    return now - created >= THEIRS_UNDATED_AFTER


def nudge_text(p, today: date) -> str | None:
    """The one nudge a promise gets, or None when it isn't time yet."""
    who = p.who or (name_from_email(p.who_email) if p.who_email else "")
    if p.direction == "mine":
        if p.due_on is None or p.due_on > today:
            return None
        when = "today" if p.due_on == today else f"on {p.due_on.strftime('%a %d %b')}"
        return f"You promised {who + ' to ' if who else ''}{p.what[0].lower() + p.what[1:]}, due {when}."
    by = f" by {p.due_on.strftime('%a %d %b')}" if p.due_on else ""
    return (f"{who or 'Someone'} said they'd {p.what[0].lower() + p.what[1:]}{by}, and hasn't written back. "
            "Want me to draft a follow-up?")


async def send_nudges(now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    sent = 0
    for uid in await asyncio.to_thread(db.users_with_open):
        user_id = str(uid)
        try:
            tz = await asyncio.to_thread(_tz, user_id)
            local = now.astimezone(tz)
            if not 9 <= local.hour < DAY_HOURS[1]:
                continue
            chase = None
            for p in await asyncio.to_thread(db.open_for_nudges, user_id):
                if p.direction == "theirs":
                    if not late(p, local.date(), now):
                        continue
                    if chase is None:
                        chase = (await asyncio.to_thread(access, user_id))["chase"]
                    if not chase:
                        continue
                text = nudge_text(p, local.date())
                if not text or not await asyncio.to_thread(db.mark_nudged, p.id):
                    continue
                await tell(user_id, text, url=f"/kept?promise={p.id}", tag=f"promise-{p.id}")
                sent += 1
        except Exception as e:  # noqa: BLE001 - one user's failure doesn't stop the rest
            log.warning("promise nudges failed", user_id=user_id, error=str(e)[:200])
    return sent


def chase_prompt(p: db.PromiseOut) -> str:
    """What "Chase" asks the agent. The promise's words came from someone's
    email, so they're quoted and capped; sending still waits for the user."""
    who = p.who or name_from_email(p.who_email) or "them"
    by = f", due {date.fromisoformat(p.due_on).strftime('%a %d %b')}" if p.due_on else ""
    to = f" ({p.who_email})" if p.who_email else ""
    where = " Reply in the same Gmail thread if you can find it." if p.thread_ref else ""
    return (f"Draft a short, polite follow-up email to {who}{to} about what they promised: \"{p.what[:200]}\"{by}. "
            f"Friendly, not pushy, two or three sentences.{where} Show me the draft before sending.")


# ------------------------------------------------------------ the scheduler's tick

async def tick(now: datetime | None = None) -> None:
    """Every scheduler tick: read due users' email, ask about meetings that
    just ended, and (every NUDGES_EVERY_S) send nudges."""
    global _last_nudges
    now = now or datetime.now(UTC)
    for user_id in await asyncio.to_thread(google_users, "calendar"):
        try:
            state = await asyncio.to_thread(db.scan_state, user_id)
            at = state["meetings_at"]
            if at and now - (at if at.tzinfo else at.replace(tzinfo=UTC)) < MEETINGS_EVERY:
                continue
            if not (await asyncio.to_thread(access, user_id))["meetings"]:
                continue
            await check_meetings(user_id, now)
        except Exception as e:  # noqa: BLE001
            log.warning("promise meetings check failed", user_id=user_id, error=str(e)[:200])
    for user_id in await asyncio.to_thread(google_users, "gmail"):
        try:
            state = await asyncio.to_thread(db.scan_state, user_id)
            at = state["email_at"]
            if not state["email_on"] or (at and now - (at if at.tzinfo else at.replace(tzinfo=UTC)) < EMAIL_EVERY):
                continue
            if not (await asyncio.to_thread(access, user_id))["email"] or not await asyncio.to_thread(_can_spend, user_id):
                continue
            await scan_email(user_id, now)
        except Exception as e:  # noqa: BLE001
            log.warning("promise email read failed", user_id=user_id, error=str(e)[:200])
    if time.monotonic() - _last_nudges >= NUDGES_EVERY_S:
        _last_nudges = time.monotonic()
        await send_nudges(now)
