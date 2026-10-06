"""What the user usually asks at this time of day, for the living stag on Today.

Tapping the stag offers the request the user makes most often in the current
part of the day, learned from their own messages over the last 30 days. Each
message is sorted into a kind by whole-word keywords (no model call, so it is
instant and free) and counted by the local hour it was sent. A kind counts as
a habit once it has happened ``MIN_SEEN`` times in that part of the day;
until then the stag offers a sensible default for the hour.

Nothing is stored: the suggestion is worked out from the transcript each time
GET /today runs.
"""

import re
from collections import Counter
from datetime import datetime, timedelta

MIN_SEEN = 3
LOOKBACK_DAYS = 30

# Parts of the day, in local hours [start, end).
WINDOWS = [(0, 5), (5, 10), (10, 12), (12, 14), (14, 18), (18, 21), (21, 24)]

# kind -> (whole-word pattern, chip label, prompt sent when the chip is tapped)
KINDS: dict[str, tuple[str, str, str]] = {
    "brief": (r"brief|my day|today's plan|what's on today|morning", "Brief me",
              "Give me my brief for today: the weather, my calendar, reminders and anything important in my email."),
    "inbox": (r"inbox|emails?|mail|unread|gmail", "Summarise my inbox",
              "Summarise my unread email from today and tell me which ones need a reply."),
    "replies": (r"reply|replies|respond|write back|draft", "Draft my replies",
                "Who is waiting for a reply from me? Draft short replies for the important ones."),
    "calendar": (r"calendar|meeting|schedule|free time|availability|reschedule|move my", "Find free time",
                 "When am I free this week? Find a couple of good slots for a meeting."),
    "reminders": (r"remind|reminder|don't let me forget", "Set a reminder", "Remind me to "),
    "lists": (r"list|grocery|groceries|shopping|to-?do", "My lists", "What's on my to-do list?"),
    "weather": (r"weather|rain|umbrella|temperature|forecast", "Weather", "What's the weather like today and tomorrow?"),
    "places": (r"lunch|dinner|restaurant|cafe|near me|nearby|directions|how long to", "Places near me",
               "Find good places for lunch near me."),
    "tomorrow": (r"tomorrow|plan my|next week", "Plan tomorrow",
                 "Help me plan tomorrow: what's on my calendar, what's due, and what I should prepare tonight."),
    "files": (r"report|spreadsheet|pdf|slides|document|chart|analy[sz]e", "Make a document", "Make a "),
    "research": (r"research|compare|explain|papers?|sources", "Research something", "Research "),
}
_PATTERNS = {k: re.compile(rf"\b(?:{p})\b", re.IGNORECASE) for k, (p, _, _) in KINDS.items()}

# What to offer before a habit has formed, by part of the day.
DEFAULTS = {(0, 5): "late", (5, 10): "brief", (10, 12): "inbox", (12, 14): "places", (14, 18): "calendar",
            (18, 21): "tomorrow", (21, 24): "reminders"}


def kind_of(text: str) -> str | None:
    """The first kind whose keywords appear in the message (KINDS order breaks ties)."""
    for k, rx in _PATTERNS.items():
        if rx.search(text or ""):
            return k
    return None


def window_of(hour: int) -> tuple[int, int]:
    return next(w for w in WINDOWS if w[0] <= hour < w[1])


def _hm(h: int) -> str:
    return f"{h % 12 or 12}{'am' if h < 12 else 'pm'}" if h not in (0, 24) else "midnight"


def suggest(messages: list[tuple[datetime, str]], now: datetime) -> dict:
    """The suggestion for ``now`` (local, tz-aware) from ``(sent_at, text)`` pairs.

    Returns ``{kind, learned, count, line, chips: [{label, prompt}]}``.
    """
    win = window_of(now.hour)
    since = now - timedelta(days=LOOKBACK_DAYS)
    tz = now.tzinfo
    counts: Counter[str] = Counter()
    for at, text in messages:
        local = at.astimezone(tz) if tz else at
        if local < since or window_of(local.hour) != win:
            continue
        k = kind_of(text)
        if k:
            counts[k] += 1
    top = counts.most_common(2)
    learned = bool(top) and top[0][1] >= MIN_SEEN
    kind = top[0][0] if learned else DEFAULTS[win]

    if kind == "late":
        return {"kind": "late", "learned": False, "count": 0,
                "line": "You're up late. Want me to push tomorrow's brief back an hour so you can sleep in?",
                "chips": [{"label": "Set a reminder for the morning", "prompt": "Remind me tomorrow at 9am to "},
                          {"label": "What's on tomorrow?", "prompt": "What's on my calendar tomorrow?"}]}

    label, prompt = KINDS[kind][1], KINDS[kind][2]
    when = f"between {_hm(win[0])} and {_hm(win[1])}"
    line = (f"You usually ask me this {when}. Shall I?" if learned
            else {"brief": "Good morning. Want your brief for today?",
                  "inbox": "Mid-morning is a good time to clear email. Shall I summarise what came in?",
                  "places": "It's around lunchtime. Want somewhere good nearby?",
                  "calendar": "Want me to find free time this week?",
                  "tomorrow": "Shall we plan tomorrow?",
                  "reminders": "Anything to remember for tomorrow?"}.get(kind, "What can I do for you?"))
    chips = [{"label": label, "prompt": prompt}]
    # the second most common habit in this window, if there is one, as a second option
    if learned and len(top) > 1 and top[1][1] >= MIN_SEEN:
        chips.append({"label": KINDS[top[1][0]][1], "prompt": KINDS[top[1][0]][2]})
    return {"kind": kind, "learned": learned, "count": counts.get(kind, 0), "line": line, "chips": chips}


def recent_messages(user_id: str, limit: int = 600) -> list[tuple[datetime, str]]:
    """The user's own messages from the last LOOKBACK_DAYS, newest first."""
    from datetime import UTC

    from sqlalchemy import select

    from harness.db.base import SessionLocal
    from harness.db.models import Conversation, ConversationMessage

    since = datetime.now(UTC) - timedelta(days=LOOKBACK_DAYS)
    with SessionLocal() as s:
        rows = s.execute(
            select(ConversationMessage.created_at, ConversationMessage.content)
            .join(Conversation, Conversation.id == ConversationMessage.conversation_id)
            .where(Conversation.user_id == user_id, ConversationMessage.role == "user",
                   ConversationMessage.created_at >= since)
            .order_by(ConversationMessage.created_at.desc()).limit(limit)).all()
    return [(at, (text or "")[:500]) for at, text in rows]
