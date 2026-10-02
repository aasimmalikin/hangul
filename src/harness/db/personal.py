"""Reminders, to-do lists and notes: the everyday-assistant data.

Every function takes the JWT ``sub`` (``users.id`` as a string) and filters
by it in the WHERE clause, so one user can never read or change another's
items -- the same structural isolation as the rest of the per-user tables.
"""

from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from sqlalchemy import or_, select

from harness.db.base import SessionLocal
from harness.db.models import Note, Reminder, TodoItem

MAX_OPEN_REMINDERS = 200
MAX_ITEMS_PER_USER = 2000
MAX_NOTES_PER_USER = 2000


class LimitReached(ValueError):
    pass


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


# ------------------------------------------------------------ reminders

@dataclass
class ReminderOut:
    id: int
    text: str
    due_at: str
    status: str
    sent_at: str | None

    def as_dict(self) -> dict:
        return asdict(self)


def _rem(r: Reminder) -> ReminderOut:
    return ReminderOut(r.id, r.text, _iso(r.due_at), r.status, _iso(r.sent_at))


def add_reminder(user_id: str, text: str, due_at: datetime) -> ReminderOut:
    with SessionLocal() as s:
        open_count = s.query(Reminder).filter(Reminder.user_id == int(user_id),
                                              Reminder.status.in_(("pending", "sent"))).count()
        if open_count >= MAX_OPEN_REMINDERS:
            raise LimitReached(f"You already have {open_count} open reminders.")
        row = Reminder(user_id=int(user_id), text=text.strip()[:500], due_at=due_at.astimezone(UTC))
        s.add(row)
        s.commit()
        s.refresh(row)
        return _rem(row)


def list_reminders(user_id: str, statuses: tuple[str, ...] = ("pending", "sent"), limit: int = 50) -> list[ReminderOut]:
    with SessionLocal() as s:
        rows = s.execute(select(Reminder).where(Reminder.user_id == int(user_id), Reminder.status.in_(statuses))
                         .order_by(Reminder.due_at).limit(limit)).scalars()
        return [_rem(r) for r in rows]


def set_reminder_status(user_id: str, reminder_id: int, status: str) -> ReminderOut | None:
    """Mark done / cancelled. A foreign id behaves like a missing one."""
    with SessionLocal() as s:
        row = s.execute(select(Reminder).where(Reminder.id == reminder_id,
                                               Reminder.user_id == int(user_id))).scalar()
        if row is None:
            return None
        row.status = status
        s.commit()
        return _rem(row)


def due_reminders(now: datetime | None = None, limit: int = 100) -> list[tuple[int, Reminder]]:
    """Pending reminders whose time has come, across all users (scheduler)."""
    now = now or datetime.now(UTC)
    with SessionLocal() as s:
        rows = s.execute(select(Reminder).where(Reminder.status == "pending", Reminder.due_at <= now)
                         .order_by(Reminder.due_at).limit(limit)).scalars().all()
        s.expunge_all()
        return [(r.user_id, r) for r in rows]


def claim_due(reminder_id: int) -> bool:
    """pending -> sent, exactly once: only the worker that wins this conditional
    UPDATE delivers it, so a reminder is never emailed twice."""
    with SessionLocal() as s:
        n = (s.query(Reminder).filter(Reminder.id == reminder_id, Reminder.status == "pending")
             .update({"status": "sent", "sent_at": datetime.now(UTC)}))
        s.commit()
        return n == 1


def mark_emailed(reminder_id: int) -> None:
    with SessionLocal() as s:
        s.query(Reminder).filter(Reminder.id == reminder_id).update({"emailed": True})
        s.commit()


# ---------------------------------------------------------------- to-dos

@dataclass
class TodoOut:
    id: int
    list_name: str
    text: str
    done: bool

    def as_dict(self) -> dict:
        return asdict(self)


def _todo(t: TodoItem) -> TodoOut:
    return TodoOut(t.id, t.list_name, t.text, t.done)


def norm_list(name: str | None) -> str:
    name = (name or "").strip()[:60]
    return name[:1].upper() + name[1:] if name else "To-do"


def add_todos(user_id: str, list_name: str, items: list[str]) -> list[TodoOut]:
    items = [i.strip()[:500] for i in items if i and i.strip()]
    with SessionLocal() as s:
        count = s.query(TodoItem).filter(TodoItem.user_id == int(user_id)).count()
        if count + len(items) > MAX_ITEMS_PER_USER:
            raise LimitReached("Your lists are full; clear some finished items first.")
        rows = [TodoItem(user_id=int(user_id), list_name=norm_list(list_name), text=i) for i in items]
        s.add_all(rows)
        s.commit()
        for r in rows:
            s.refresh(r)
        return [_todo(r) for r in rows]


def list_todos(user_id: str, list_name: str | None = None, include_done: bool = False) -> list[TodoOut]:
    with SessionLocal() as s:
        q = select(TodoItem).where(TodoItem.user_id == int(user_id))
        if list_name:
            q = q.where(TodoItem.list_name.ilike(norm_list(list_name)))
        if not include_done:
            q = q.where(TodoItem.done.is_(False))
        rows = s.execute(q.order_by(TodoItem.list_name, TodoItem.done, TodoItem.created_at).limit(500)).scalars()
        return [_todo(r) for r in rows]


def list_names(user_id: str) -> list[str]:
    with SessionLocal() as s:
        return list(s.execute(select(TodoItem.list_name).where(TodoItem.user_id == int(user_id))
                              .distinct().order_by(TodoItem.list_name)).scalars())


def set_todo_done(user_id: str, item_id: int, done: bool) -> TodoOut | None:
    with SessionLocal() as s:
        row = s.execute(select(TodoItem).where(TodoItem.id == item_id, TodoItem.user_id == int(user_id))).scalar()
        if row is None:
            return None
        row.done = done
        row.done_at = datetime.now(UTC) if done else None
        s.commit()
        return _todo(row)


def delete_todo(user_id: str, item_id: int) -> bool:
    with SessionLocal() as s:
        n = s.query(TodoItem).filter(TodoItem.id == item_id, TodoItem.user_id == int(user_id)).delete()
        s.commit()
        return n == 1


def find_todos(user_id: str, text: str, list_name: str | None = None) -> list[TodoOut]:
    """Open items whose text contains ``text`` (how the model names an item)."""
    with SessionLocal() as s:
        q = select(TodoItem).where(TodoItem.user_id == int(user_id), TodoItem.done.is_(False),
                                   TodoItem.text.ilike(f"%{text.strip()}%"))
        if list_name:
            q = q.where(TodoItem.list_name.ilike(norm_list(list_name)))
        return [_todo(r) for r in s.execute(q.limit(20)).scalars()]


# ----------------------------------------------------------------- notes

@dataclass
class NoteOut:
    id: int
    text: str
    created_at: str

    def as_dict(self) -> dict:
        return asdict(self)


def _note(n: Note) -> NoteOut:
    return NoteOut(n.id, n.text, _iso(n.created_at))


def add_note(user_id: str, text: str) -> NoteOut:
    with SessionLocal() as s:
        if s.query(Note).filter(Note.user_id == int(user_id)).count() >= MAX_NOTES_PER_USER:
            raise LimitReached("You have too many notes; delete some first.")
        row = Note(user_id=int(user_id), text=text.strip()[:4000])
        s.add(row)
        s.commit()
        s.refresh(row)
        return _note(row)


def search_notes(user_id: str, query: str = "", limit: int = 20) -> list[NoteOut]:
    """Newest first; with a query, notes containing ANY of its words."""
    words = [w for w in query.split() if len(w) > 2][:8]
    with SessionLocal() as s:
        q = select(Note).where(Note.user_id == int(user_id))
        if words:
            q = q.where(or_(*[Note.text.ilike(f"%{w}%") for w in words]))
        return [_note(n) for n in s.execute(q.order_by(Note.created_at.desc()).limit(limit)).scalars()]


def delete_note(user_id: str, note_id: int) -> bool:
    with SessionLocal() as s:
        n = s.query(Note).filter(Note.id == note_id, Note.user_id == int(user_id)).delete()
        s.commit()
        return n == 1
