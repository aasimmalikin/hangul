"""Scheduled tasks: CRUD and the next-run arithmetic."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from harness.db.base import SessionLocal
from harness.db.models import ScheduledTask

MIN_EVERY_MINUTES = 15
WEEK_MINUTES = 7 * 24 * 60   # with daily_at: "weekly at HH:MM" (the Free plan's brief)
MAX_TASKS_PER_USER = 20
ALL_DAYS = 0b1111111          # ``days`` bit 0 = Monday … bit 6 = Sunday
WEEKDAYS = 0b0011111
ONCE_MINUTES = 10 ** 9        # a one-off run, for plan checks: fits every plan


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
    days: int | None = None
    run_on: date | None = None

    def public(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__ if k != "user_id"}


def _to(row: ScheduledTask) -> Task:
    return Task(id=row.id, user_id=row.user_id, title=row.title, question=row.question,
                every_minutes=row.every_minutes, daily_at=row.daily_at, connectors=list(row.connectors or []),
                mode=row.mode, enabled=row.enabled, next_run_at=row.next_run_at, last_run_at=row.last_run_at,
                last_status=row.last_status, last_run_id=row.last_run_id, last_answer=row.last_answer,
                created_at=row.created_at, deliver_email=bool(getattr(row, "deliver_email", False)),
                days=row.days, run_on=row.run_on)


def _hhmm(daily_at: str | None) -> tuple[int, int]:
    hh, mm = (int(x) for x in (daily_at or "09:00").split(":"))
    return hh, mm


def interval_minutes(every_minutes: int | None, daily_at: str | None, days: int | None = None,
                     run_on: date | None = None) -> int:
    """How often a schedule runs, for plan checks."""
    if run_on:
        return ONCE_MINUTES
    if daily_at and days:
        return WEEK_MINUTES if (days & ALL_DAYS).bit_count() == 1 else 24 * 60
    if daily_at:
        return WEEK_MINUTES if every_minutes == WEEK_MINUTES else 24 * 60
    return every_minutes or 24 * 60


def compute_next_run(every_minutes: int | None, daily_at: str | None, tz: str, after: datetime | None = None,
                     *, ran: bool = False, days: int | None = None, run_on: date | None = None) -> datetime | None:
    """Next run time, or None when there is none (a one-off that has run). ``ran`` =
    called as a run starts, so a weekly task skips ahead a week (when created or
    retimed it runs at the next HH:MM). ``days`` limits a daily time to those
    weekdays; ``run_on`` makes it a single run on that local date."""
    now = after or datetime.now(UTC)
    zone = ZoneInfo(tz or "UTC")
    if run_on:
        return None if ran else datetime.combine(run_on, time(*_hhmm(daily_at)), tzinfo=zone).astimezone(UTC)
    if days and daily_at:
        local = now.astimezone(zone)
        for i in range(8):
            d = local.date() + timedelta(days=i)
            candidate = datetime.combine(d, time(*_hhmm(daily_at)), tzinfo=zone)
            if days >> d.weekday() & 1 and candidate > local:
                return candidate.astimezone(UTC)
    weekly = bool(daily_at) and every_minutes == WEEK_MINUTES
    if weekly:
        now = now + timedelta(days=6) if ran else now
    elif every_minutes:
        return now + timedelta(minutes=max(MIN_EVERY_MINUTES, every_minutes))
    hh, mm = _hhmm(daily_at)
    local = now.astimezone(zone)
    candidate = local.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if candidate <= local:
        candidate += timedelta(days=1)
    return candidate.astimezone(UTC)


def lead(connectors: list | None, daily_at: str | None, question: str = "") -> timedelta:
    """How early a time-of-day task runs: LEAD_MINUTES when its actions wait for the
    user's OK (harness.preapproval), so the approval reaches them before the time they picked."""
    from harness.preapproval import LEAD_MINUTES, asks_first
    return (timedelta(minutes=LEAD_MINUTES) if daily_at and asks_first(list(connectors or []), question)
            else timedelta(0))


def next_for(every_minutes: int | None, daily_at: str | None, tz: str, connectors: list | None, *,
             days: int | None = None, run_on: date | None = None, ran: bool = False,
             after: datetime | None = None, question: str = "") -> datetime | None:
    """compute_next_run, moved earlier by the task's lead. Worked out from now + lead,
    so a run that starts early doesn't land on the same slot again."""
    early = lead(connectors, daily_at, question)
    nxt = compute_next_run(every_minutes, daily_at, tz, (after or datetime.now(UTC)) + early,
                           ran=ran, days=days, run_on=run_on)
    return None if nxt is None else nxt - early


def _first_day(days: int) -> int:
    """The earliest weekday in a mask, alone (a weekdays task slowed to weekly)."""
    return days & -days


def create_task(user_id: str, *, title: str, question: str, every_minutes: int | None, daily_at: str | None,
                connectors: list[str], mode: str, tz: str, deliver_email: bool = False, days: int | None = None,
                run_on: date | None = None) -> Task:
    if not (every_minutes or daily_at):
        raise ValueError("a schedule needs every_minutes or daily_at")
    if (days or run_on) and not daily_at:
        raise ValueError("pick a time of day for this schedule")
    if days is not None and not 0 < days <= ALL_DAYS:
        raise ValueError("pick at least one day")
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
        now = datetime.now(UTC)
        first = compute_next_run(every_minutes, daily_at, tz, days=days, run_on=run_on)
        if run_on and first <= now:
            raise ValueError("that time has already passed; pick a later one")
        # early by the lead when its actions need an OK; a one-off due within the lead runs now
        first = max(first - lead(connectors, daily_at, question), now) if run_on else \
            next_for(every_minutes, daily_at, tz, connectors, days=days, question=question)
        row = ScheduledTask(user_id=int(user_id), title=title[:120], question=question[:4000],
                            every_minutes=every_minutes, daily_at=daily_at, connectors=list(connectors), mode=mode,
                            deliver_email=deliver_email, days=days, run_on=run_on,
                            next_run_at=first)
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
        if enabled:
            now = datetime.now(UTC)
            nxt = compute_next_run(row.every_minutes, row.daily_at, tz, days=row.days, run_on=row.run_on)
            if row.run_on and nxt <= now:
                raise ValueError("this one-off task's time has passed; delete it and schedule a new one")
            row.next_run_at = (max(nxt - lead(row.connectors, row.daily_at, row.question), now) if row.run_on else
                               next_for(row.every_minutes, row.daily_at, tz, row.connectors, days=row.days,
                                        question=row.question))
        row.enabled = enabled
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
        if row.run_on:                                   # a one-off: this is its only run
            row.next_run_at, row.enabled = None, False
        elif weekly and interval_minutes(row.every_minutes, row.daily_at, row.days) < WEEK_MINUTES:
            row.next_run_at = (next_for(None, row.daily_at, tz, row.connectors, ran=True, days=_first_day(row.days),
                                        question=row.question)
                               if row.daily_at and row.days else
                               next_for(WEEK_MINUTES, row.daily_at, tz, row.connectors, ran=True, question=row.question)
                               if row.daily_at
                               else datetime.now(UTC) + timedelta(minutes=WEEK_MINUTES))
        else:
            row.next_run_at = next_for(row.every_minutes, row.daily_at, tz, row.connectors, ran=True, days=row.days,
                                       question=row.question)
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


def waiting_since(before: datetime) -> list[tuple[int, int, str]]:
    """(task id, user id, run id) of task runs still waiting for the user since before ``before``."""
    with SessionLocal() as s:
        rows = s.execute(select(ScheduledTask.id, ScheduledTask.user_id, ScheduledTask.last_run_id)
                         .where(ScheduledTask.last_status == "needs_approval",
                                ScheduledTask.last_run_id.is_not(None),
                                ScheduledTask.last_run_at < before)).all()
    return [(r[0], r[1], r[2]) for r in rows]


def waiting_runs(user_id: str) -> list[tuple[str, str]]:
    """(title, run id) of this user's task runs waiting for them, newest first."""
    with SessionLocal() as s:
        rows = s.execute(select(ScheduledTask.title, ScheduledTask.last_run_id)
                         .where(ScheduledTask.user_id == int(user_id), ScheduledTask.last_status == "needs_approval",
                                ScheduledTask.last_run_id.is_not(None))
                         .order_by(ScheduledTask.last_run_at.desc())).all()
    return [(r[0], r[1]) for r in rows]


def set_status(task_id: int, status: str) -> None:
    with SessionLocal() as s:
        row = s.get(ScheduledTask, task_id)
        if row is not None:
            row.last_status = status
            s.commit()


def retime_daily(user_id: str, tz: str) -> int:
    """Re-aim every enabled daily task at HH:MM in the new timezone (after
    the user's device moved), so "daily at 08:00" stays 08:00 where they are."""
    with SessionLocal() as s:
        rows = s.execute(select(ScheduledTask).where(ScheduledTask.user_id == int(user_id),
                                                     ScheduledTask.daily_at.is_not(None),
                                                     ScheduledTask.enabled.is_(True))).scalars().all()
        for row in rows:
            if row.run_on:          # a one-off keeps its wall-clock time in the new zone if still ahead
                nxt = (compute_next_run(None, row.daily_at, tz, run_on=row.run_on)
                       - lead(row.connectors, row.daily_at, row.question))
                row.next_run_at = nxt if nxt > datetime.now(UTC) else row.next_run_at
                continue
            row.next_run_at = next_for(row.every_minutes, row.daily_at, tz, row.connectors, days=row.days,
                                       question=row.question)
        s.commit()
        return len(rows)
