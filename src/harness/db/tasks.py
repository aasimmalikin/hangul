"""Scheduled tasks: CRUD and the next-run arithmetic."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from harness.db.base import SessionLocal
from harness.db.models import ScheduledTask

MIN_EVERY_MINUTES = 15
WEEK_MINUTES = 7 * 24 * 60   # with daily_at: "weekly at HH:MM" (the Free plan's brief)
MAX_TASKS_PER_USER = 20


@dataclass
class Task:
    id: int
    user_id: int
    title: str
    question: str
    every_minutes: int | None
    daily_at: str | None
    connectors: list
    mode: str
    enabled: bool
    next_run_at: datetime | None
    last_run_at: datetime | None
    last_status: str
    last_run_id: str | None
    last_answer: str
    created_at: datetime | None
    deliver_email: bool = False

    def public(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__ if k != "user_id"}


def _to(row: ScheduledTask) -> Task:
    return Task(id=row.id, user_id=row.user_id, title=row.title, question=row.question,
                every_minutes=row.every_minutes, daily_at=row.daily_at, connectors=list(row.connectors or []),
                mode=row.mode, enabled=row.enabled, next_run_at=row.next_run_at, last_run_at=row.last_run_at,
                last_status=row.last_status, last_run_id=row.last_run_id, last_answer=row.last_answer,
                created_at=row.created_at, deliver_email=bool(getattr(row, "deliver_email", False)))


def interval_minutes(every_minutes: int | None, daily_at: str | None) -> int:
    """How often a schedule runs, for plan checks."""
    if daily_at:
        return WEEK_MINUTES if every_minutes == WEEK_MINUTES else 24 * 60
    return every_minutes or 24 * 60


def compute_next_run(every_minutes: int | None, daily_at: str | None, tz: str, after: datetime | None = None,
                     *, ran: bool = False) -> datetime:
    """Next run time. ``ran`` = called as a run starts, so a weekly task skips
    ahead a week (when created or retimed it runs at the next HH:MM)."""
    now = after or datetime.now(UTC)
    weekly = bool(daily_at) and every_minutes == WEEK_MINUTES
    if weekly:
        now = now + timedelta(days=6) if ran else now
    elif every_minutes:
        return now + timedelta(minutes=max(MIN_EVERY_MINUTES, every_minutes))
    hh, mm = (int(x) for x in (daily_at or "09:00").split(":"))
    zone = ZoneInfo(tz or "UTC")
    local = now.astimezone(zone)
    candidate = local.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if candidate <= local:
        candidate += timedelta(days=1)
    return candidate.astimezone(UTC)


def create_task(user_id: str, *, title: str, question: str, every_minutes: int | None, daily_at: str | None,
                connectors: list[str], mode: str, tz: str, deliver_email: bool = False) -> Task:
    if not (every_minutes or daily_at):
        raise ValueError("a schedule needs every_minutes or daily_at")
    if every_minutes and every_minutes < MIN_EVERY_MINUTES:
        raise ValueError(f"every_minutes must be at least {MIN_EVERY_MINUTES}")
    if daily_at:
        try:
            hh, mm = (int(x) for x in daily_at.split(":"))
            assert 0 <= hh < 24 and 0 <= mm < 60
        except (ValueError, AssertionError) as e:
            raise ValueError("daily_at must be HH:MM") from e
    with SessionLocal() as s:
        n = s.execute(select(ScheduledTask).where(ScheduledTask.user_id == int(user_id))).scalars().all()
        if len(n) >= MAX_TASKS_PER_USER:
            raise ValueError(f"at most {MAX_TASKS_PER_USER} scheduled tasks")
        row = ScheduledTask(user_id=int(user_id), title=title[:120], question=question[:4000],
                            every_minutes=every_minutes, daily_at=daily_at, connectors=list(connectors), mode=mode,
                            deliver_email=deliver_email, next_run_at=compute_next_run(every_minutes, daily_at, tz))
        s.add(row)
        s.commit()
        s.refresh(row)
        return _to(row)


def list_tasks(user_id: str) -> list[Task]:
    with SessionLocal() as s:
        rows = s.execute(select(ScheduledTask).where(ScheduledTask.user_id == int(user_id))
                         .order_by(ScheduledTask.created_at.desc())).scalars().all()
        return [_to(r) for r in rows]


def get_task(user_id: str, task_id: int) -> Task | None:
    with SessionLocal() as s:
        row = s.get(ScheduledTask, task_id)
        return _to(row) if row is not None and row.user_id == int(user_id) else None


def delete_task(user_id: str, task_id: int) -> bool:
    with SessionLocal() as s:
        row = s.get(ScheduledTask, task_id)
        if row is None or row.user_id != int(user_id):
            return False
        s.delete(row)
        s.commit()
        return True


def set_enabled(user_id: str, task_id: int, enabled: bool, tz: str) -> Task | None:
    with SessionLocal() as s:
        row = s.get(ScheduledTask, task_id)
        if row is None or row.user_id != int(user_id):
            return None
        row.enabled = enabled
        if enabled:
            row.next_run_at = compute_next_run(row.every_minutes, row.daily_at, tz)
        s.commit()
        s.refresh(row)
        return _to(row)


def due_tasks(now: datetime | None = None, limit: int = 20) -> list[Task]:
    now = now or datetime.now(UTC)
    with SessionLocal() as s:
        rows = s.execute(select(ScheduledTask).where(ScheduledTask.enabled.is_(True), ScheduledTask.next_run_at <= now)
                         .order_by(ScheduledTask.next_run_at).limit(limit)).scalars().all()
        return [_to(r) for r in rows]


def mark_started(task_id: int, tz: str, *, weekly: bool = False) -> None:
    """Advance next_run_at before running so a slow run is never picked twice.
    ``weekly`` slows a more frequent task to once a week (a plan that no
    longer includes it, e.g. after a downgrade to Free)."""
    with SessionLocal() as s:
        row = s.get(ScheduledTask, task_id)
        if row is None:
            return
        row.last_run_at = datetime.now(UTC)
        row.last_status = "running"
        if weekly and interval_minutes(row.every_minutes, row.daily_at) < WEEK_MINUTES:
            row.next_run_at = (compute_next_run(WEEK_MINUTES, row.daily_at, tz, ran=True) if row.daily_at
                               else datetime.now(UTC) + timedelta(minutes=WEEK_MINUTES))
        else:
            row.next_run_at = compute_next_run(row.every_minutes, row.daily_at, tz, ran=True)
        s.commit()


def mark_finished(task_id: int, *, status: str, run_id: str | None, answer: str) -> None:
    with SessionLocal() as s:
        row = s.get(ScheduledTask, task_id)
        if row is None:
            return
        row.last_status = status
        row.last_run_id = run_id
        row.last_answer = (answer or "")[:4000]
        s.commit()


def retime_daily(user_id: str, tz: str) -> int:
    """Re-aim every enabled daily task at HH:MM in the new timezone (after
    the user's device moved), so "daily at 08:00" stays 08:00 where they are."""
    with SessionLocal() as s:
        rows = s.execute(select(ScheduledTask).where(ScheduledTask.user_id == int(user_id),
                                                     ScheduledTask.daily_at.is_not(None),
                                                     ScheduledTask.enabled.is_(True))).scalars().all()
        for row in rows:
            row.next_run_at = compute_next_run(row.every_minutes, row.daily_at, tz)
        s.commit()
        return len(rows)
