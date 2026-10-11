"""The Kept tab: everything the user asked Hangul to do that lasts beyond the
reply, as one list of rows -- what they said, what Hangul did, and its state.

Rows come from the tables that already hold the thing (reminders, scheduled
tasks, runs waiting for approval, list items, notes, memories) plus
``kept_actions``, the log of outward actions with no row of their own.

States:
- ``needs_you``: an action paused for the user's OK.
- ``coming``:    a reminder or scheduled task that hasn't happened yet.
- ``done``:      a reminder that went off, a task that ran, an action taken.
- ``kept``:      undated things Hangul holds: list items, notes, memories.

Every query filters on the caller's id, like the rest of the per-user tables.
"""

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select

from harness.db.base import SessionLocal
from harness.db.models import (
    Conversation,
    KeptAction,
    Note,
    Promise,
    Reminder,
    ScheduledTask,
    Thread,
    TodoItem,
    UserMemory,
)
from harness.logging import log
from harness.provenance import SAID_MAX, Source, app_for, describe

PAST_DAYS = 7            # how far back the timeline reaches
APPROVAL_DAYS = 7        # older waiting approvals still work in their chat, but aren't listed
LIMIT = 100

# the follow-up questions /approve resumes a run with; never the user's words
RESUME_PROMPTS = ("Briefly confirm what was just done", "The user answered your clarifying question")

_STOP = {"what", "did", "ask", "asked", "about", "the", "my", "for", "and", "with", "that", "this", "from",
         "when", "have", "any", "all", "show", "find", "tell", "me", "you", "i", "to", "of", "a", "an", "on",
         "in", "is", "was", "were", "hangul", "please", "things", "thing"}


@dataclass
class Item:
    id: str
    kind: str                   # approval | reminder | task | task_run | action | promise | todo | note | memory
    state: str                  # needs_you | coming | done | kept
    did: str
    said: str | None = None
    when: str | None = None
    app: str | None = None
    conversation_id: str | None = None
    ref: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return asdict(self)


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=UTC)).isoformat()


def _aware(dt: datetime | None) -> datetime | None:
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=UTC)


# ------------------------------------------------------------- recording

def record_action(src: Source, tool: str, args: dict) -> None:
    """Log one completed outward action (called from guarded_dispatch)."""
    app = app_for(tool)
    if app is None:
        return
    from harness.vault.redact import redactor
    did = redactor.scrub_text(describe(tool, args, done=True))[:300]
    with SessionLocal() as s:
        s.add(KeptAction(user_id=src.user_id, conversation_id=src.conversation_id, said=src.said or None,
                         tool=tool[:100], app=app, did=did))
        s.commit()


def run_question(messages: list[dict]) -> str:
    """The user's question behind a run: its last user message that isn't
    one of /approve's own follow-ups."""
    for m in reversed(messages or []):
        if m.get("role") != "user":
            continue
        text = m.get("content")
        if isinstance(text, list):          # multi-part content
            text = " ".join(p.get("text", "") for p in text if isinstance(p, dict))
        text = " ".join(str(text or "").split())
        if text and not text.startswith(RESUME_PROMPTS):
            return text[:SAID_MAX]
    return ""


# ---------------------------------------------------------------- reading

def _clock(hhmm: str) -> str:
    """"16:10" (stored) -> "4:10 PM" (shown), like the Settings task form."""
    try:
        h, m = (int(x) for x in hhmm.split(":"))
    except ValueError:
        return hhmm
    return f"{h % 12 or 12}:{m:02d} {'PM' if h >= 12 else 'AM'}"


_DAY = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _schedule(t: ScheduledTask) -> str:
    if t.daily_at and getattr(t, "run_on", None):
        return f"Once on {t.run_on.strftime('%a')} {t.run_on.day} {t.run_on.strftime('%b')} at {_clock(t.daily_at)}"
    days = getattr(t, "days", None)
    if t.daily_at and days:
        names = [d for i, d in enumerate(_DAY) if days >> i & 1]
        if days == 0b0011111:
            return f"Every weekday at {_clock(t.daily_at)}"
        if days == 0b1111111:
            return f"Every day at {_clock(t.daily_at)}"
        if len(names) == 1:
            return f"Every {names[0]} at {_clock(t.daily_at)}"
        return f"{', '.join(names)} at {_clock(t.daily_at)}"
    if t.daily_at and t.every_minutes == 7 * 24 * 60:
        return f"Every week at {_clock(t.daily_at)}"
    if t.daily_at:
        return f"Every day at {_clock(t.daily_at)}"
    m = t.every_minutes or 0
    return f"Every {m // 60} hours" if m and m % 60 == 0 else f"Every {m} minutes"


def _words(q: str) -> list[str]:
    return [w for w in (x.strip(".,!?\"'“”") for x in q.lower().split()) if len(w) > 1 and w not in _STOP][:8]


def _like(words: list[str], *cols):
    return or_(*[c.ilike(f"%{w}%") for w in words for c in cols])


def _approvals(s, user_id: str, now: datetime, words: list[str] | None) -> list[Item]:
    since = now - timedelta(days=APPROVAL_DAYS)
    rows = s.execute(
        select(Thread).outerjoin(Conversation, Conversation.id == Thread.conversation_id)
        .where(Thread.user_id == user_id, Thread.status == "pending_approval", Thread.updated_at >= since,
               or_(Thread.conversation_id.is_(None), Conversation.active.is_(True)))
        .order_by(Thread.updated_at.desc()).limit(20)).scalars().all()
    out = []
    for r in rows:
        pending = r.pending_tool or {}
        name = pending.get("name", "")
        if not name or name == "ask_user":
            # a clarifying question isn't an instruction; it shows in its chat
            continue
        said = run_question(r.message or [])
        did = describe(name, pending.get("arguments") or {}, done=False)
        if words and not any(w in f"{said} {did}".lower() for w in words):
            continue
        out.append(Item(f"approval:{r.thread_id}", "approval", "needs_you", did, said or None, _iso(r.updated_at),
                        app_for(name), r.conversation_id, {"run_id": r.thread_id, "tool": name}))
    return out


def _reminders(s, uid: int, now: datetime, words: list[str] | None) -> list[Item]:
    q = select(Reminder).where(Reminder.user_id == uid, Reminder.status != "cancelled")
    if words:
        q = q.where(_like(words, Reminder.text, Reminder.said))
    else:
        q = q.where(or_(Reminder.status == "pending", Reminder.due_at >= now - timedelta(days=PAST_DAYS)))
    out = []
    for r in s.execute(q.order_by(Reminder.due_at.desc()).limit(LIMIT)).scalars():
        state = "coming" if r.status == "pending" else "done"
        did = f"Reminder: {r.text}" if state == "coming" else f"Reminded you: {r.text}"
        out.append(Item(f"reminder:{r.id}", "reminder", state, did, r.said, _iso(r.due_at), "Reminder",
                        r.conversation_id, {"id": r.id, "status": r.status}))
    return out


def _tasks(s, uid: int, now: datetime, words: list[str] | None) -> list[Item]:
    q = select(ScheduledTask).where(ScheduledTask.user_id == uid)
    if words:
        q = q.where(_like(words, ScheduledTask.title, ScheduledTask.question))
    out = []
    found = list(s.execute(q.limit(LIMIT)).scalars())
    # each run made a chat: link it, or "Ran and is waiting for you" has nothing to open
    run_ids = [t.last_run_id for t in found if t.last_run_id]
    chat_of = dict(s.execute(select(Thread.thread_id, Thread.conversation_id)
                             .where(Thread.thread_id.in_(run_ids))).all()) if run_ids else {}
    for t in found:
        sched = _schedule(t) + (", emailed to you" if t.deliver_email else "")
        if t.enabled:
            out.append(Item(f"task:{t.id}", "task", "coming", f"{t.title} · {sched}", t.question,
                            _iso(t.next_run_at), "Scheduled", None, {"id": t.id, "repeats": True}))
        last = _aware(t.last_run_at)
        if last and (words or last >= now - timedelta(days=PAST_DAYS)):
            ran = {"done": "Ran", "needs_approval": "Ran and is waiting for you", "failed": "Tried and failed",
                   "needs_plan": "Skipped (needs a plan)",
                   "expired": "Waited for you, then expired"}.get(t.last_status, "Ran")
            out.append(Item(f"task_run:{t.id}", "task_run", "done", f"{ran}: {t.title}", t.question,
                            _iso(last), "Scheduled", chat_of.get(t.last_run_id), {"id": t.id, "run_id": t.last_run_id}))
    return out


def _actions(s, user_id: str, now: datetime, words: list[str] | None) -> list[Item]:
    q = select(KeptAction).where(KeptAction.user_id == user_id)
    if words:
        q = q.where(_like(words, KeptAction.did, KeptAction.said))
    else:
        q = q.where(KeptAction.created_at >= now - timedelta(days=PAST_DAYS))
    return [Item(f"action:{a.id}", "action", "done", a.did, a.said, _iso(a.created_at), a.app, a.conversation_id,
                 {"id": a.id, "tool": a.tool})
            for a in s.execute(q.order_by(KeptAction.created_at.desc()).limit(LIMIT)).scalars()]


def promise_line(p: Promise) -> str:
    who = p.who or p.who_email or ""
    if p.status == "done":
        return f"Kept: {p.what}" + (f" ({'for' if p.direction == 'mine' else 'from'} {who})" if who else "")
    if p.status == "dropped":
        return f"Dropped: {p.what}"
    if p.direction == "mine":
        return f"You promised{' ' + who if who else ''}: {p.what}"
    return f"{who or 'Someone'} promised you: {p.what}"


def _promises(s, uid: int, now: datetime, words: list[str] | None) -> list[Item]:
    """Open promises (dated ones on their day, the rest on the day they were made)
    and ones kept or dropped in the last week."""
    q = select(Promise).where(Promise.user_id == uid)
    if words:
        q = q.where(_like(words, Promise.what, Promise.who, Promise.who_email, Promise.said))
    else:
        q = q.where(or_(Promise.status == "open", Promise.done_at >= now - timedelta(days=PAST_DAYS)))
    out = []
    for p in s.execute(q.order_by(Promise.created_at.desc()).limit(LIMIT)).scalars():
        state = "coming" if p.status == "open" else "done"
        when = (p.done_at if p.status != "open" else None) or (
            datetime(p.due_on.year, p.due_on.month, p.due_on.day, 12, tzinfo=UTC) if p.due_on else p.created_at)
        out.append(Item(f"promise:{p.id}", "promise", state, promise_line(p), p.said or (p.quote or None), _iso(when),
                        "Promise", p.conversation_id,
                        {"id": p.id, "direction": p.direction, "status": p.status, "source": p.source,
                         "due_on": p.due_on.isoformat() if p.due_on else None, "who": p.who,
                         "who_email": p.who_email, "wrote_back": p.last_contact_at is not None,
                         "chased": p.chased_at is not None}))
    return out


def _held(s, uid: int, words: list[str]) -> list[Item]:
    """Undated things, only when searching (the drawer reads its own routes)."""
    out = []
    for t in s.execute(select(TodoItem).where(TodoItem.user_id == uid, _like(words, TodoItem.text, TodoItem.said))
                       .order_by(TodoItem.created_at.desc()).limit(50)).scalars():
        out.append(Item(f"todo:{t.id}", "todo", "done" if t.done else "kept",
                        f"{'Ticked off' if t.done else 'On'} {t.list_name}: {t.text}", t.said,
                        _iso(t.done_at or t.created_at), "List", t.conversation_id,
                        {"id": t.id, "list": t.list_name, "done": t.done}))
    for n in s.execute(select(Note).where(Note.user_id == uid, _like(words, Note.text, Note.said))
                       .order_by(Note.created_at.desc()).limit(50)).scalars():
        out.append(Item(f"note:{n.id}", "note", "kept", f"Note: {n.text[:200]}", n.said, _iso(n.created_at),
                        "Note", n.conversation_id, {"id": n.id}))
    for m in s.execute(select(UserMemory).where(UserMemory.user_id == uid, UserMemory.active.is_(True),
                                                _like(words, UserMemory.content, UserMemory.said))
                       .order_by(UserMemory.created_at.desc()).limit(50)).scalars():
        out.append(Item(f"memory:{m.id}", "memory", "kept", f"Remembered: {m.content[:200]}", m.said,
                        _iso(m.created_at), "Memory", m.conversation_id, {"id": m.id}))
    return out


def _holding(s, uid: int) -> dict:
    lists: dict[str, int] = {}
    for name, in s.execute(select(TodoItem.list_name).where(TodoItem.user_id == uid, TodoItem.done.is_(False))):
        lists[name] = lists.get(name, 0) + 1
    notes = s.query(Note).filter(Note.user_id == uid).count()
    memories = s.query(UserMemory).filter(UserMemory.user_id == uid, UserMemory.active.is_(True)).count()
    return {"lists": lists, "notes": notes, "memories": memories}


def _sort_key(i: Item) -> str:
    return i.when or ""


def kept(user_id: str, q: str = "", now: datetime | None = None) -> dict:
    """The Kept list. Without ``q``: the timeline (last week, and everything
    still to come) plus counts for the drawer. With ``q``: matching rows from
    all time, undated ones included."""
    now = now or datetime.now(UTC)
    words = _words(q) if q.strip() else None
    if q.strip() and not words:
        words = [q.strip().lower()[:40]]
    uid = int(user_id)
    with SessionLocal() as s:
        items: list[Item] = []
        for part, fn, arg in (("approvals", _approvals, user_id), ("reminders", _reminders, uid),
                              ("tasks", _tasks, uid), ("actions", _actions, user_id),
                              ("promises", _promises, uid)):
            try:
                items += fn(s, arg, now, words)
            except Exception as e:  # noqa: BLE001 - one broken source must not blank the page
                log.warning("kept source failed", part=part, error=str(e))
                s.rollback()
        if words:
            items += _held(s, uid, words)
        holding = _holding(s, uid)
    items.sort(key=_sort_key)
    return {"now": now.isoformat(), "query": q.strip() or None, "items": [i.as_dict() for i in items],
            "needs_you": sum(1 for i in items if i.state == "needs_you"), "holding": holding}


def needs_you_count(user_id: str, now: datetime | None = None) -> int:
    """The tab badge: approvals waiting on the user (no other source is read)."""
    now = now or datetime.now(UTC)
    with SessionLocal() as s:
        tools = s.execute(
            select(Thread.pending_tool).outerjoin(Conversation, Conversation.id == Thread.conversation_id)
            .where(Thread.user_id == user_id, Thread.status == "pending_approval",
                   Thread.updated_at >= now - timedelta(days=APPROVAL_DAYS),
                   or_(Thread.conversation_id.is_(None), Conversation.active.is_(True))).limit(20)).scalars()
        return sum(1 for t in tools if (t or {}).get("name") not in (None, "", "ask_user"))
