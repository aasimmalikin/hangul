"""The morning check-in on Today: "How are you feeling?".

One row per user per local day (re-answering replaces it). Three things come
out of it:

- ``reply``: what Hangul says back, straight away and without a model call;
- ``prompt_line``: today's mood in the system prompt, so answers adapt (a tired
  day gets fewer suggestions and gentler wording). It is part of the answer
  cache key too (``ask.py``), because it can change the answer;
- ``streak``: consecutive days with a check-in, ending today (or yesterday, if
  today's isn't in yet). It is shown as encouragement, never as a debt.
"""

from datetime import date, timedelta

from sqlalchemy import select

MOODS: dict[str, tuple[str, str]] = {
    # mood -> (what Hangul says back, how it should behave today)
    "great": ("Love that. Let's make the most of it. Tell me what matters most today and I'll keep the rest out of your way.",
              "great: they have energy today, so it is fine to suggest getting ahead on things"),
    "ok": ("Okay. I'll keep today simple and look after the reminders.",
           "okay: keep things simple and to the point"),
    "tired": ("Sorry to hear that. I'll keep today light: fewer suggestions, and only the things that can't wait.",
              "tired: keep plans light, suggest fewer things, offer to move what can wait, and word things gently"),
    "busy": ("Got it. I'll keep it short today and only bring up what can't wait.",
             "swamped: be brief, prioritise ruthlessly, and only raise what truly can't wait"),
}


def reply_for(mood: str) -> str:
    return MOODS[mood][0]


def prompt_line(mood: str | None) -> str:
    """The line for the system prompt, or "" when there is no check-in today."""
    if mood not in MOODS:
        return ""
    return f"How they said they feel today: {MOODS[mood][1]}."


def streak_from(days: set[str], today: date) -> tuple[int, list[bool]]:
    """(consecutive days ending today, or yesterday if today has no check-in yet;
    the last 7 days oldest first, True = checked in)."""
    week = [(today - timedelta(days=6 - i)).isoformat() in days for i in range(7)]
    d = today if today.isoformat() in days else today - timedelta(days=1)
    n = 0
    while d.isoformat() in days:
        n += 1
        d -= timedelta(days=1)
    return n, week


def record(user_id: str, day: date, mood: str) -> None:
    from harness.db.base import SessionLocal
    from harness.db.models import MoodCheckin
    if mood not in MOODS:
        raise ValueError(f"unknown mood {mood!r}")
    with SessionLocal() as s:
        row = s.execute(select(MoodCheckin).where(MoodCheckin.user_id == user_id, MoodCheckin.day == day.isoformat())).scalar_one_or_none()
        if row is None:
            s.add(MoodCheckin(user_id=user_id, day=day.isoformat(), mood=mood))
        else:
            row.mood = mood
        s.commit()


def state(user_id: str, today: date) -> dict:
    """``{mood, reply, streak, week}`` for GET /today (mood/reply null until today's check-in)."""
    from harness.db.base import SessionLocal
    from harness.db.models import MoodCheckin
    since = (today - timedelta(days=400)).isoformat()
    with SessionLocal() as s:
        rows = s.execute(select(MoodCheckin.day, MoodCheckin.mood)
                         .where(MoodCheckin.user_id == user_id, MoodCheckin.day >= since)).all()
    by_day = {d: m for d, m in rows}
    n, week = streak_from(set(by_day), today)
    mood = by_day.get(today.isoformat())
    return {"mood": mood, "reply": reply_for(mood) if mood in MOODS else None, "streak": n, "week": week}


def today_mood(user_id: str, today: date) -> str | None:
    from harness.db.base import SessionLocal
    from harness.db.models import MoodCheckin
    with SessionLocal() as s:
        return s.execute(select(MoodCheckin.mood).where(MoodCheckin.user_id == user_id, MoodCheckin.day == today.isoformat())).scalar_one_or_none()


def mood_now(user_id: str, timezone: str | None) -> str | None:
    """Today's mood in the user's local date, or None (no check-in, or the DB is unavailable)."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    try:
        return today_mood(user_id, datetime.now(ZoneInfo(timezone or "UTC")).date())
    except Exception:  # noqa: BLE001 - the mood is a nicety; never fail a question over it
        return None
