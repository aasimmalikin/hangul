"""GET /today: the home screen's brief, assembled from what Hangul already
has -- greeting and local time, weather for the home city, the rest of today's
calendar, reminders and open to-dos, approvals waiting on the user, and
important unread mail. Also: "Leave by" for the next event with a place,
birthdays in the coming week (Contacts), and after 18:00 a "Tomorrow" section.

Each section is fetched concurrently with its own timeout and simply left out
(null) if it fails or isn't connected, so the screen always renders. The
external parts (weather, calendar, mail) are cached per user for two minutes;
reminders, lists and approvals are always fresh.
"""

import asyncio
import time
from datetime import datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select

from harness import habits
from harness.api.auth import get_current_user
from harness.db import checkins
from harness.logging import log

router = APIRouter()

CACHE_S = 120
_cache: dict[str, tuple[float, dict]] = {}

# Birthdays change rarely and the contact list can be long: read it at most every 6 h.
BIRTHDAY_CACHE_S = 6 * 3600
_birthdays_cache: dict[str, tuple[float, str, list]] = {}      # user -> (at, local date, birthdays)
# A route between the same two places barely changes within a quarter of an hour.
ROUTE_CACHE_S = 15 * 60
_route_cache: dict[tuple[str, str], tuple[float, dict | None]] = {}
LEAVE_BUFFER_MIN = 10          # "leave by" = start - travel - this
LEAVE_LOOKAHEAD_H = 12         # only the next event starting within this many hours
EVENING_HOUR = 18              # from here on the screen also shows tomorrow

# "Needs you" lists approvals from the last day only: one asked for last night
# still shows in the morning, an abandoned one from last week doesn't (the chat
# still has it, and approving there works as before).
APPROVAL_FRESH_S = 24 * 3600


def _first_name(user_id: str, display: str) -> str:
    if display:
        return display.split()[0]
    try:
        from harness.db.base import SessionLocal
        from harness.db.models import User
        with SessionLocal() as s:
            name = s.execute(select(User.name).where(User.id == int(user_id))).scalar()
        return (name or "").split()[0] if name else ""
    except Exception:  # noqa: BLE001
        return ""


def _pending_approvals(user_id: str) -> list[dict]:
    """Approvals waiting on the user from the last day, newest first, leaving
    out ones whose chat was deleted."""
    from datetime import UTC

    from sqlalchemy import or_

    from harness.db.base import SessionLocal
    from harness.db.models import Conversation, Thread
    since = datetime.now(UTC) - timedelta(seconds=APPROVAL_FRESH_S)
    with SessionLocal() as s:
        rows = s.execute(
            select(Thread)
            .outerjoin(Conversation, Conversation.id == Thread.conversation_id)
            .where(Thread.user_id == user_id, Thread.status == "pending_approval", Thread.updated_at >= since,
                   or_(Thread.conversation_id.is_(None), Conversation.active.is_(True)))
            .order_by(Thread.updated_at.desc()).limit(5)).scalars().all()
        return [{"run_id": r.thread_id, "conversation_id": r.conversation_id,
                 "tool": (r.pending_tool or {}).get("name", ""),
                 "since": r.updated_at.isoformat() if r.updated_at else None} for r in rows]


async def _timed(coro, seconds: float = 6.0):
    try:
        return await asyncio.wait_for(coro, seconds)
    except Exception as e:  # noqa: BLE001 - a section that fails is just left out
        log.info("today section skipped", error=f"{type(e).__name__}: {e}"[:200])
        return None


async def _weather(city: str):
    if not city:
        return None
    from harness.tools.builtin.weather import weather
    out = await weather(city, days=1)
    return getattr(out, "ui", None)


async def _calendar(user_id: str, tz: ZoneInfo):
    from harness.connectors.google_rest import make_google_tools
    now = datetime.now(tz)
    end = now.replace(hour=23, minute=59, second=0, microsecond=0)
    if now.hour >= EVENING_HOUR:                          # evening: fetch tomorrow too (split in today())
        end = end + timedelta(days=1)
    tool = next(t for t in make_google_tools(user_id) if t.name == "calendar__list_events")
    out = await tool.handler(time_min=now.isoformat(), time_max=end.isoformat(), max_results=10)
    if isinstance(out, str):                     # "No events…" or an error (not connected, scope missing…)
        return [] if out.startswith("No events") else None
    return (out.ui or {}).get("events", [])


def mail_query(email_from: str | None) -> str:
    """Important unread mail from the last 2 days, from other people: not mail
    the user sent themselves, and not Hangul's own emails to them (reminders,
    the brief, task results), which arrive from ``email_from``."""
    import re
    q = "is:unread newer_than:2d (is:important OR category:primary) -from:me"
    m = re.search(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", email_from or "")
    return f"{q} -from:{m.group(0)}" if m else q


async def _mail(user_id: str):
    from harness.config import get_settings
    from harness.connectors.google_rest import make_google_tools
    tool = next(t for t in make_google_tools(user_id) if t.name == "gmail__search_messages")
    out = await tool.handler(query=mail_query(get_settings().email_from), max_results=4)
    if isinstance(out, str):
        return [] if "No messages" in out else None
    return [{k: m.get(k) for k in ("id", "thread_id", "from", "subject", "snippet", "date")}
            for m in (out.ui or {}).get("messages", [])]


def _local_date(start: str, tz: ZoneInfo):
    """The local calendar date an event starts on ("2026-10-04" all-day dates included)."""
    if len(start) == 10:
        return datetime.fromisoformat(start).date()
    return datetime.fromisoformat(start.replace("Z", "+00:00")).astimezone(tz).date()


def _has_place(location: str | None) -> bool:
    """A street address or place, not a video link ("https://meet…", "Zoom")."""
    loc = (location or "").strip().lower()
    return bool(loc) and not loc.startswith(("http://", "https://")) and not any(
        w in loc for w in ("meet.google", "zoom.us", "teams.microsoft", "webex"))


def next_with_place(events: list[dict], now: datetime) -> dict | None:
    """The next timed event that starts within LEAVE_LOOKAHEAD_H and has a place."""
    for e in events:
        if e.get("all_day") or not _has_place(e.get("location")):
            continue
        start = datetime.fromisoformat(str(e.get("start", "")).replace("Z", "+00:00"))
        if now < start <= now + timedelta(hours=LEAVE_LOOKAHEAD_H):
            return e
    return None


async def _route(home: str, place: str) -> dict | None:
    """Driving time home -> place ({minutes, link}), cached; None if it can't be routed."""
    key = (home.lower(), place.lower())
    hit = _route_cache.get(key)
    if hit and time.monotonic() - hit[0] < ROUTE_CACHE_S:
        return hit[1]
    from harness.tools.builtin.maps import travel_time
    out = await travel_time(home, place, "driving")
    ui = getattr(out, "ui", None) or {}
    route = {"minutes": ui["minutes"], "link": ui.get("link")} if ui.get("minutes") is not None else None
    _route_cache[key] = (time.monotonic(), route)
    return route


async def _leave_by(home: str, events: list[dict] | None, now: datetime) -> dict | None:
    """When to set off for the next event with a place. Without a home address
    the card still shows the event and asks for one."""
    e = next_with_place(events or [], now)
    if e is None:
        return None
    card = {"summary": e.get("summary"), "start": e.get("start"), "location": e.get("location")}
    if not home:
        return {**card, "needs_home": True}
    route = await _timed(_route(home, e["location"]), 8)
    if not route:
        return {**card, "minutes": None}         # couldn't route: show the event, no time
    start = datetime.fromisoformat(str(e["start"]).replace("Z", "+00:00"))
    leave = start - timedelta(minutes=route["minutes"] + LEAVE_BUFFER_MIN)
    return {**card, "minutes": route["minutes"], "link": route["link"],
            "leave_at": max(leave, now).isoformat(), "late": leave <= now}


async def _replies(user_id: str) -> list:
    from datetime import UTC

    from harness.connectors.replies import replies_owed
    return await replies_owed(user_id, datetime.now(UTC))


async def _birthdays(user_id: str, today_local) -> list | None:
    hit = _birthdays_cache.get(user_id)
    if hit and time.monotonic() - hit[0] < BIRTHDAY_CACHE_S and hit[1] == today_local.isoformat():
        return hit[2]
    from harness.connectors.google_rest import upcoming_birthdays
    found = await upcoming_birthdays(user_id, today_local, 7)
    _birthdays_cache[user_id] = (time.monotonic(), today_local.isoformat(), found)
    return found


@router.get("/today")
async def today(quick: bool = False, user: dict = Depends(get_current_user)) -> dict:
    """The Today screen. ``quick=1`` answers at once from the database and the
    cache only (no Google, weather or maps call), so the page can draw the
    greeting, reminders and to-dos straight away; the slow parts are then null
    and ``partial`` is true, and the page fetches the full brief after it."""
    from harness.connectors.auto import connected_apps
    from harness.db import personal
    from harness.db.settings import get_settings as user_settings

    uid = user["user_id"]
    prefs = await asyncio.to_thread(user_settings, uid)
    tz = ZoneInfo(prefs.timezone or "UTC")
    now = datetime.now(tz)
    hour = now.hour
    tomorrow_date = (now + timedelta(days=1)).date()
    def skip():                                         # a section that isn't fetched (a fresh coroutine each time)
        return asyncio.sleep(0, None)

    hit = _cache.get(uid)
    cached = hit[1] if hit and time.monotonic() - hit[0] < CACHE_S and hit[1].get("city") == prefs.city else None

    async def external_and_leave(connected: list[str]):
        """Weather, calendar and mail (cached), then when to leave -- which needs the calendar."""
        external = cached
        if external is None:
            weather_ui, events, mail = await asyncio.gather(
                _timed(_weather(prefs.city)),
                _timed(_calendar(uid, tz)) if "calendar" in connected else skip(),
                _timed(_mail(uid)) if "gmail" in connected else skip(),
            )
            external = {"city": prefs.city, "weather": weather_ui, "events": events, "emails": mail}
            _cache[uid] = (time.monotonic(), external)
        # the calendar fetch runs into tomorrow in the evening: split it by local date
        events_today = None if external["events"] is None else [
            e for e in external["events"] if _local_date(e["start"], tz) <= now.date()]
        leave_by = (await _timed(_leave_by(prefs.home_address, events_today, now), 9)) if events_today else None
        return external, events_today, leave_by

    async def slow():
        # everything here can take seconds; what doesn't depend on the calendar runs alongside it
        connected = await _timed(connected_apps(uid), 5) or []
        (external, events_today, leave_by), birthdays, replies = await asyncio.gather(
            external_and_leave(connected),
            _timed(_birthdays(uid, now.date())) if "contacts" in connected else skip(),
            _timed(_replies(uid), 9) if "gmail" in connected else skip(),
        )
        return connected, external, events_today, leave_by, birthdays, replies

    async def quick_parts():
        external = cached or {"city": prefs.city, "weather": None, "events": None, "emails": None}
        events_today = None if external["events"] is None else [
            e for e in external["events"] if _local_date(e["start"], tz) <= now.date()]
        return [], external, events_today, None, None, None

    (connected, external, events_today, leave_by, birthdays, replies), \
        reminders, todos, approvals, history, checkin, memory = await asyncio.gather(
            quick_parts() if quick else slow(),
            _timed(asyncio.to_thread(personal.list_reminders, uid, ("sent", "pending"), 8)),
            _timed(asyncio.to_thread(personal.list_todos, uid)),
            _timed(asyncio.to_thread(_pending_approvals, uid)),
            _timed(asyncio.to_thread(habits.recent_messages, uid), 4),
            _timed(asyncio.to_thread(checkins.state, uid, now.date()), 4),
            _timed(asyncio.to_thread(memory_of_the_day, uid, now.date()), 4),
        )
    all_events = external["events"]
    events_tomorrow = [] if all_events is None else [e for e in all_events if _local_date(e["start"], tz) == tomorrow_date]

    # a mail already under "Replies you owe" isn't repeated under "Needs you"
    owed_threads = {r["thread_id"] for r in (replies or [])}
    emails = external["emails"]
    if emails and owed_threads:
        emails = [m for m in emails if m.get("thread_id") not in owed_threads]

    # fired-and-not-dismissed, plus anything still to come today
    end_of_day = now.replace(hour=23, minute=59, second=59)
    due = [r.as_dict() for r in (reminders or [])
           if r.status == "sent" or datetime.fromisoformat(r.due_at) <= end_of_day]
    tomorrow = None
    if hour >= EVENING_HOUR:
        later = [r.as_dict() for r in (reminders or [])
                 if r.status == "pending" and datetime.fromisoformat(r.due_at).astimezone(tz).date() == tomorrow_date]
        tomorrow = {"date_label": (now + timedelta(days=1)).strftime("%A, %d %B"),
                    "events": events_tomorrow if all_events is not None else None, "reminders": later}
    return {
        "greeting": "Good morning" if hour < 12 else "Good afternoon" if hour < 17 else "Good evening",
        "name": await asyncio.to_thread(_first_name, uid, prefs.display_name),
        "date_label": now.strftime("%A, %d %B"),
        "timezone": prefs.timezone,
        "city": prefs.city,
        "weather": external["weather"],
        "events": events_today,                  # None = Calendar not connected
        "tomorrow": tomorrow,                    # None before 18:00
        "leave_by": leave_by,                    # None = no event with a place coming up
        "birthdays": birthdays,                  # None = Contacts not connected
        "emails": emails,                        # None = Gmail not connected
        "replies": replies,                      # replies owed; None = Gmail not connected
        "reminders": due,
        "todos": [t.as_dict() for t in (todos or [])[:8]],
        "approvals": approvals or [],
        "connected": connected,
        # what tapping the stag offers: the user's usual request at this time of day (harness/habits.py)
        "suggestion": habits.suggest(history or [], now),
        # the morning check-in: today's mood (null until answered), Hangul's reply, the streak (db/checkins.py)
        "checkin": checkin,
        # one thing the user told Hangul, brought back on Today ("You told me…"); rotates daily
        "memory": memory,
        # quick=1: Google, weather and maps parts weren't fetched (null unless cached); the full brief follows
        "partial": quick,
    }


def memory_of_the_day(user_id: str, day) -> dict | None:
    """One remembered item, a different one each day, so Today can bring it back."""
    from harness.db.memory import list_active
    rows = list_active(user_id)
    if not rows:
        return None
    r = rows[day.toordinal() % len(rows)]
    return {"id": r.id, "content": r.content, "kind": r.kind}


class CheckinRequest(BaseModel):
    mood: Literal["great", "ok", "tired", "busy"]


@router.post("/today/checkin")
async def checkin(req: CheckinRequest, user: dict = Depends(get_current_user)) -> dict:
    """The morning check-in: store today's mood (local date) and answer with
    Hangul's reply and the streak. Answering again the same day replaces it."""
    from harness.db.settings import get_settings as user_settings
    uid = user["user_id"]
    prefs = await asyncio.to_thread(user_settings, uid)
    today = datetime.now(ZoneInfo(prefs.timezone or "UTC")).date()
    await asyncio.to_thread(checkins.record, uid, today, req.mood)
    return await asyncio.to_thread(checkins.state, uid, today)
