"""Missions (harness.missions): jobs Hangul carries through over days, and the
trust the owner has given it. A foreign id behaves exactly like a missing one
(None -> 404).

A mission is unique per (user, kind, business, day): ``start`` returns None
when that job already exists, so a scheduler tick that runs twice (or two
replicas) never starts it twice.
"""

from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from harness.db.base import SessionLocal
from harness.db.models import Mission, MissionTrust

OPEN = ("active", "waiting")


def _uid(user_id: str) -> int:
    return int(user_id)


def view(m: Mission) -> dict:
    steps = list(m.steps or [])
    return {"id": m.id, "kind": m.kind, "business_id": m.business_id or None, "target_day": m.target_day.isoformat(),
            "status": m.status, "steps": steps, "data": dict(m.data or {}),
            "done": sum(1 for s in steps if s.get("state") in ("done", "skipped")), "total": len(steps),
            "created_at": m.created_at.isoformat() if m.created_at else None,
            "updated_at": m.updated_at.isoformat() if m.updated_at else None}


def start(user_id: str, kind: str, target_day: date, steps: list[dict], *, business_id: int = 0,
          data: dict | None = None) -> dict | None:
    with SessionLocal() as s:
        m = Mission(user_id=_uid(user_id), kind=kind, business_id=business_id or 0, target_day=target_day,
                    steps=steps, data=data or {}, status="active")
        s.add(m)
        try:
            s.commit()
        except IntegrityError:
            s.rollback()
            return None
        s.refresh(m)
        return view(m)


def exists(user_id: str, kind: str, target_day: date, business_id: int = 0) -> bool:
    with SessionLocal() as s:
        return s.execute(select(Mission.id).where(
            Mission.user_id == _uid(user_id), Mission.kind == kind, Mission.target_day == target_day,
            Mission.business_id == (business_id or 0))).first() is not None


def get(user_id: str, mission_id: int) -> dict | None:
    with SessionLocal() as s:
        m = s.get(Mission, mission_id)
        return view(m) if m is not None and m.user_id == _uid(user_id) else None


def owner(mission_id: int) -> str | None:
    with SessionLocal() as s:
        m = s.get(Mission, mission_id)
        return str(m.user_id) if m is not None else None


def list_for(user_id: str, *, limit: int = 30, business_id: int | None = None, kind: str | None = None) -> list[dict]:
    with SessionLocal() as s:
        q = select(Mission).where(Mission.user_id == _uid(user_id))
        if business_id is not None:
            q = q.where(Mission.business_id == business_id)
        if kind:
            q = q.where(Mission.kind == kind)
        return [view(m) for m in s.execute(q.order_by(Mission.target_day.desc(), Mission.id.desc()).limit(limit)).scalars()]


def open_missions() -> list[tuple[str, dict]]:
    """Every mission still being worked on, for the scheduler tick."""
    with SessionLocal() as s:
        rows = s.execute(select(Mission).where(Mission.status.in_(OPEN)).order_by(Mission.id)).scalars()
        return [(str(m.user_id), view(m)) for m in rows]


def save(mission_id: int, *, status: str | None = None, steps: list | None = None, data: dict | None = None,
         expect: str | None = None) -> dict | None:
    """Write the mission back. ``data`` is merged into what's stored. ``expect``:
    only when the status is still that one (a decision taken once, even if two
    taps race); returns None when it wasn't."""
    with SessionLocal() as s:
        m = s.get(Mission, mission_id)
        if m is None or (expect is not None and m.status != expect):
            return None
        if status is not None:
            m.status = status
        if steps is not None:
            m.steps = [dict(x) for x in steps]
        if data:
            m.data = {**(m.data or {}), **data}
        m.updated_at = datetime.now().astimezone()
        s.commit()
        s.refresh(m)
        return view(m)


def measured(business_id: int, kind: str = "slow_day") -> list[dict]:
    """Finished missions of a business whose outcome was measured (for learning)."""
    with SessionLocal() as s:
        rows = s.execute(select(Mission).where(Mission.business_id == business_id, Mission.kind == kind,
                                               Mission.status == "done").order_by(Mission.target_day)).scalars()
        return [view(m) for m in rows if (m.data or {}).get("outcome")]


def between(user_id: str, start: date, end: date, kind: str = "slow_day") -> list[dict]:
    """A user's missions whose day falls in [start, end)."""
    with SessionLocal() as s:
        rows = s.execute(select(Mission).where(Mission.user_id == _uid(user_id), Mission.kind == kind,
                                               Mission.target_day >= start, Mission.target_day < end)
                         .order_by(Mission.target_day)).scalars()
        return [view(m) for m in rows]


def users_with(kind: str, since: date) -> list[str]:
    with SessionLocal() as s:
        rows = s.execute(select(Mission.user_id).where(Mission.kind == kind, Mission.target_day >= since).distinct())
        return [str(r[0]) for r in rows]


# ------------------------------------------------------------ earned autonomy

def _trust_view(t: MissionTrust) -> dict:
    return {"scope": t.scope, "streak": t.streak, "auto": bool(t.auto), "offered": bool(t.offered)}


def trust(user_id: str, scope: str) -> dict:
    with SessionLocal() as s:
        t = s.execute(select(MissionTrust).where(MissionTrust.user_id == _uid(user_id),
                                                 MissionTrust.scope == scope)).scalar_one_or_none()
        return _trust_view(t) if t else {"scope": scope, "streak": 0, "auto": False, "offered": False}


def trusts(user_id: str) -> list[dict]:
    with SessionLocal() as s:
        rows = s.execute(select(MissionTrust).where(MissionTrust.user_id == _uid(user_id))
                         .order_by(MissionTrust.scope)).scalars()
        return [_trust_view(t) for t in rows]


def set_trust(user_id: str, scope: str, **fields) -> dict:
    """Upsert; ``streak_add`` adds to the streak, the other fields are set."""
    with SessionLocal() as s:
        t = s.execute(select(MissionTrust).where(MissionTrust.user_id == _uid(user_id),
                                                 MissionTrust.scope == scope)).scalar_one_or_none()
        if t is None:
            t = MissionTrust(user_id=_uid(user_id), scope=scope, streak=0, auto=False, offered=False)
            s.add(t)
        add = fields.pop("streak_add", 0)
        t.streak = (t.streak or 0) + add
        for k in ("streak", "auto", "offered"):
            if k in fields:
                setattr(t, k, fields[k])
        t.updated_at = datetime.now().astimezone()
        s.commit()
        s.refresh(t)
        return _trust_view(t)
