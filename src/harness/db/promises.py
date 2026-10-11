"""Promises: what the user said they'd do, and what others said they'd do for
them (harness.promises). Every function takes the JWT ``sub`` and filters on it,
like the rest of the per-user tables; a foreign id behaves like a missing one.
"""

from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime

from sqlalchemy import func, select

from harness.db.base import SessionLocal
from harness.db.models import Promise, PromiseScan
from harness.provenance import stamp

MAX_OPEN = 500
SEEN_KEEP = 400            # Gmail message ids remembered per user
ASKED_KEEP = 40            # meetings asked about, remembered per user
DIRECTIONS = ("mine", "theirs")
STATUSES = ("open", "done", "dropped")


class LimitReached(ValueError):
    pass


def _iso(v) -> str | None:
    if v is None:
        return None
    if isinstance(v, datetime) and v.tzinfo is None:
        v = v.replace(tzinfo=UTC)
    return v.isoformat()


@dataclass
class PromiseOut:
    id: int
    direction: str
    what: str
    who: str
    who_email: str
    due_on: str | None
    source: str
    quote: str
    status: str
    thread_ref: str
    last_contact_at: str | None
    chased_at: str | None
    created_at: str | None
    conversation_id: str | None
    said: str | None

    def as_dict(self) -> dict:
        return asdict(self)


def _out(p: Promise) -> PromiseOut:
    return PromiseOut(p.id, p.direction, p.what, p.who or "", p.who_email or "", _iso(p.due_on), p.source,
                      p.quote or "", p.status, p.thread_ref or "", _iso(p.last_contact_at), _iso(p.chased_at),
                      _iso(p.created_at), p.conversation_id, p.said)


def add(user_id: str, direction: str, what: str, *, who: str = "", who_email: str = "", due_on: date | None = None,
        source: str = "chat", source_ref: str = "", thread_ref: str = "", quote: str = "") -> PromiseOut:
    """A new open promise. The same open promise (direction, words, person) is
    returned instead of stored twice."""
    if direction not in DIRECTIONS:
        raise ValueError("direction must be mine or theirs")
    what = " ".join(what.split())[:300]
    if not what:
        raise ValueError("say what was promised")
    who_email = who_email.strip().lower()[:255]
    with SessionLocal() as s:
        same = s.execute(select(Promise).where(
            Promise.user_id == int(user_id), Promise.status == "open", Promise.direction == direction,
            func.lower(Promise.what) == what.lower(), Promise.who_email == who_email)).scalars().first()
        if same is not None:
            if due_on and not same.due_on:
                same.due_on = due_on
                s.commit()
            return _out(same)
        n = s.query(Promise).filter(Promise.user_id == int(user_id), Promise.status == "open").count()
        if n >= MAX_OPEN:
            raise LimitReached(f"You already have {n} open promises; mark some kept or dropped first.")
        row = Promise(user_id=int(user_id), direction=direction, what=what, who=" ".join(who.split())[:120],
                      who_email=who_email, due_on=due_on, source=source[:16], source_ref=source_ref[:128],
                      thread_ref=thread_ref[:128], quote=" ".join(quote.split())[:500], **stamp())
        s.add(row)
        s.commit()
        s.refresh(row)
        return _out(row)


def list_for(user_id: str, status: str | None = "open", limit: int = 200) -> list[PromiseOut]:
    """Open ones by due date (undated last); otherwise newest first."""
    with SessionLocal() as s:
        q = select(Promise).where(Promise.user_id == int(user_id))
        if status:
            q = q.where(Promise.status == status)
        rows = s.execute(q.order_by(Promise.created_at.desc()).limit(limit)).scalars().all()
        out = [_out(r) for r in rows]
    if status == "open":
        out.sort(key=lambda p: (p.due_on is None, p.due_on or "", p.created_at or ""))
    return out


def get(user_id: str, promise_id: int) -> PromiseOut | None:
    with SessionLocal() as s:
        row = s.execute(select(Promise).where(Promise.id == promise_id, Promise.user_id == int(user_id))).scalar()
        return _out(row) if row else None


def update(user_id: str, promise_id: int, **fields) -> PromiseOut | None:
    """status (open | done | dropped), what, who, due_on (a date or None)."""
    with SessionLocal() as s:
        row = s.execute(select(Promise).where(Promise.id == promise_id, Promise.user_id == int(user_id))).scalar()
        if row is None:
            return None
        if "status" in fields:
            if fields["status"] not in STATUSES:
                raise ValueError("status must be open, done or dropped")
            row.status = fields["status"]
            row.done_at = datetime.now(UTC) if row.status != "open" else None
        if fields.get("what"):
            row.what = " ".join(str(fields["what"]).split())[:300]
        if "who" in fields and fields["who"] is not None:
            row.who = " ".join(str(fields["who"]).split())[:120]
        if "due_on" in fields:
            row.due_on = fields["due_on"]
            row.nudged_at = None                       # a new date gets its own nudge
        s.commit()
        return _out(row)


def find(user_id: str, text: str) -> list[PromiseOut]:
    """Open promises whose words or person contain ``text`` (how the model names one)."""
    t = f"%{text.strip()}%"
    with SessionLocal() as s:
        rows = s.execute(select(Promise).where(Promise.user_id == int(user_id), Promise.status == "open",
                                               (Promise.what.ilike(t)) | (Promise.who.ilike(t)) |
                                               (Promise.who_email.ilike(t))).limit(20)).scalars()
        return [_out(r) for r in rows]


def with_people(user_id: str, emails: list[str], limit: int = 6) -> list[PromiseOut]:
    """Open promises with any of these people (meeting prep)."""
    emails = [e.strip().lower() for e in emails if e and "@" in e]
    if not emails:
        return []
    with SessionLocal() as s:
        rows = s.execute(select(Promise).where(Promise.user_id == int(user_id), Promise.status == "open",
                                               Promise.who_email.in_(emails))
                         .order_by(Promise.created_at).limit(limit)).scalars()
        return [_out(r) for r in rows]


def seen_threads(user_id: str) -> dict[str, list[tuple[int, str, datetime]]]:
    """Open promises found in email, by Gmail thread: (id, direction, created_at)."""
    with SessionLocal() as s:
        rows = s.execute(select(Promise.id, Promise.thread_ref, Promise.direction, Promise.created_at)
                         .where(Promise.user_id == int(user_id), Promise.status == "open",
                                Promise.thread_ref != "")).all()
    out: dict[str, list] = {}
    for pid, thread, direction, created in rows:
        out.setdefault(thread, []).append((pid, direction, created if created.tzinfo else created.replace(tzinfo=UTC)))
    return out


def mark_contact(user_id: str, ids: list[int], when: datetime) -> int:
    if not ids:
        return 0
    with SessionLocal() as s:
        n = (s.query(Promise).filter(Promise.user_id == int(user_id), Promise.id.in_(ids))
             .update({"last_contact_at": when}, synchronize_session=False))
        s.commit()
        return n


def mark_nudged(promise_id: int) -> bool:
    """Claim the one nudge a promise gets for its date (conditional, so two
    workers never both send it)."""
    with SessionLocal() as s:
        n = (s.query(Promise).filter(Promise.id == promise_id, Promise.nudged_at.is_(None))
             .update({"nudged_at": datetime.now(UTC)}, synchronize_session=False))
        s.commit()
        return n == 1


def mark_chased(user_id: str, promise_id: int) -> PromiseOut | None:
    with SessionLocal() as s:
        row = s.execute(select(Promise).where(Promise.id == promise_id, Promise.user_id == int(user_id))).scalar()
        if row is None:
            return None
        row.chased_at = datetime.now(UTC)
        s.commit()
        return _out(row)


def users_with_open() -> list[int]:
    with SessionLocal() as s:
        return list(s.execute(select(Promise.user_id).where(Promise.status == "open").distinct()).scalars())


def open_for_nudges(user_id: str) -> list[Promise]:
    """Open, dated or theirs, not yet nudged for their date: what the scheduler may nudge about."""
    with SessionLocal() as s:
        rows = s.execute(select(Promise).where(Promise.user_id == int(user_id), Promise.status == "open",
                                               Promise.nudged_at.is_(None))).scalars().all()
        s.expunge_all()
        return list(rows)


def counts(user_id: str) -> dict:
    with SessionLocal() as s:
        rows = s.execute(select(Promise.direction, func.count()).where(
            Promise.user_id == int(user_id), Promise.status == "open").group_by(Promise.direction)).all()
    c = dict(rows)
    return {"mine": c.get("mine", 0), "theirs": c.get("theirs", 0)}


# ------------------------------------------------------------ scan state

def scan_state(user_id: str) -> dict:
    with SessionLocal() as s:
        row = s.get(PromiseScan, int(user_id))
        if row is None:
            return {"email_on": True, "email_at": None, "meetings_at": None, "seen": [], "asked": []}
        return {"email_on": row.email_on, "email_at": row.email_at, "meetings_at": row.meetings_at,
                "seen": list(row.seen or []), "asked": list(row.asked or [])}


def save_scan(user_id: str, **fields) -> None:
    """email_on, email_at, meetings_at; ``seen_add`` / ``asked_add`` append (newest kept)."""
    with SessionLocal() as s:
        row = s.get(PromiseScan, int(user_id))
        if row is None:
            row = PromiseScan(user_id=int(user_id), seen=[], asked=[])
            s.add(row)
        for k in ("email_on", "email_at", "meetings_at"):
            if k in fields:
                setattr(row, k, fields[k])
        if fields.get("seen_add"):
            row.seen = (list(row.seen or []) + [x for x in fields["seen_add"] if x not in (row.seen or [])])[-SEEN_KEEP:]
        if fields.get("asked_add"):
            row.asked = (list(row.asked or []) + list(fields["asked_add"]))[-ASKED_KEEP:]
        s.commit()
