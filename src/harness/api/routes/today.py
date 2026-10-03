"""GET /today: the home screen's brief, assembled from what Hangul already
has -- greeting and local time, weather for the home city, the rest of today's
calendar, reminders and open to-dos, approvals waiting on the user, and
important unread mail.

Each section is fetched concurrently with its own timeout and simply left out
(null) if it fails or isn't connected, so the screen always renders. The
external parts (weather, calendar, mail) are cached per user for two minutes;
reminders, lists and approvals are always fresh.
"""

import asyncio
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from sqlalchemy import select

from harness.api.auth import get_current_user
from harness.logging import log

router = APIRouter()

CACHE_S = 120
_cache: dict[str, tuple[float, dict]] = {}


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
    from harness.db.base import SessionLocal
    from harness.db.models import Thread
    with SessionLocal() as s:
        rows = s.execute(select(Thread).where(Thread.user_id == user_id, Thread.status == "pending_approval")
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
    if now.hour >= 18:                                    # evening: show tomorrow too
        end = end + timedelta(days=1)
    tool = next(t for t in make_google_tools(user_id) if t.name == "calendar__list_events")
    out = await tool.handler(time_min=now.isoformat(), time_max=end.isoformat(), max_results=6)
    if isinstance(out, str):                     # "No events…" or an error (not connected, scope missing…)
        return [] if out.startswith("No events") else None
    return (out.ui or {}).get("events", [])


async def _mail(user_id: str):
    from harness.connectors.google_rest import make_google_tools
    tool = next(t for t in make_google_tools(user_id) if t.name == "gmail__search_messages")
    out = await tool.handler(query="is:unread newer_than:2d (is:important OR category:primary)", max_results=4)
    if isinstance(out, str):
        return [] if "No messages" in out else None
    return [{k: m.get(k) for k in ("id", "thread_id", "from", "subject", "snippet", "date")}
            for m in (out.ui or {}).get("messages", [])]


@router.get("/today")
async def today(user: dict = Depends(get_current_user)) -> dict:
    from harness.connectors.auto import connected_apps
    from harness.db import personal
    from harness.db.settings import get_settings as user_settings

    uid = user["user_id"]
    prefs = await asyncio.to_thread(user_settings, uid)
    tz = ZoneInfo(prefs.timezone or "UTC")
    now = datetime.now(tz)
    hour = now.hour

    connected = await _timed(connected_apps(uid), 5) or []
    reminders, todos, approvals = await asyncio.gather(
        _timed(asyncio.to_thread(personal.list_reminders, uid, ("sent", "pending"), 8)),
        _timed(asyncio.to_thread(personal.list_todos, uid)),
        _timed(asyncio.to_thread(_pending_approvals, uid)),
    )

    hit = _cache.get(uid)
    if hit and time.monotonic() - hit[0] < CACHE_S and hit[1].get("city") == prefs.city:
        external = hit[1]
    else:
        weather_ui, events, mail = await asyncio.gather(
            _timed(_weather(prefs.city)),
            _timed(_calendar(uid, tz)) if "calendar" in connected else asyncio.sleep(0, None),
            _timed(_mail(uid)) if "gmail" in connected else asyncio.sleep(0, None),
        )
        external = {"city": prefs.city, "weather": weather_ui, "events": events, "emails": mail}
        _cache[uid] = (time.monotonic(), external)

    # fired-and-not-dismissed, plus anything still to come today
    end_of_day = now.replace(hour=23, minute=59, second=59)
    due = [r.as_dict() for r in (reminders or [])
           if r.status == "sent" or datetime.fromisoformat(r.due_at) <= end_of_day]
    return {
        "greeting": "Good morning" if hour < 12 else "Good afternoon" if hour < 17 else "Good evening",
        "name": await asyncio.to_thread(_first_name, uid, prefs.display_name),
        "date_label": now.strftime("%A, %d %B"),
        "timezone": prefs.timezone,
        "city": prefs.city,
        "weather": external["weather"],
        "events": external["events"],            # None = Calendar not connected
        "emails": external["emails"],            # None = Gmail not connected
        "reminders": due,
        "todos": [t.as_dict() for t in (todos or [])[:8]],
        "approvals": approvals or [],
        "connected": connected,
    }
