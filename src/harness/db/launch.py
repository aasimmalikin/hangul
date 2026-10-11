"""The user's launch plans (harness.launch): CRUD, and how many sourced plans
their plan includes this month.

A foreign id behaves exactly like a missing one (None -> 404). The numbers
(``economics``) are computed from the stored items and assumptions on every
read, so the dashboard and the export can never disagree.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select

from harness.db.base import SessionLocal
from harness.db.models import LaunchPlan
from harness.launch import economics

# a build that stopped saving progress this long ago died with its process
STALE_S = 15 * 60
LIST_LIMIT = 50


def _uid(user_id: str) -> int:
    return int(user_id)


def _status(p: LaunchPlan) -> tuple[str, str]:
    if p.status == "sourcing" and p.updated_at is not None:
        updated = p.updated_at if p.updated_at.tzinfo else p.updated_at.replace(tzinfo=UTC)
        if datetime.now(UTC) - updated > timedelta(seconds=STALE_S):
            return "failed", "The search was interrupted. Try again: the parts already found are kept."
    return p.status, p.error


def view(p: LaunchPlan) -> dict:
    status, error = _status(p)
    budget = (p.answers or {}).get("budget")
    return {
        "id": p.id, "title": p.title, "kind": p.kind, "city": p.city, "area": p.area,
        "conversation_id": p.conversation_id, "answers": p.answers or {}, "items": p.items or [],
        "assumptions": p.assumptions or {}, "benchmarks": p.benchmarks or [], "suppliers": p.suppliers or [],
        "status": status, "error": error, "sourced": bool(p.sourced), "progress": p.progress or {},
        "refreshes": p.refreshes or 0,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
        "economics": economics.compute(p.items or [], p.assumptions or {}, budget),
    }


def summary(p: LaunchPlan) -> dict:
    v = view(p)
    e = v["economics"]
    return {k: v[k] for k in ("id", "title", "kind", "city", "area", "status", "sourced", "created_at", "updated_at")} | {
        "startup_total": e["startup_total"], "breakeven_per_day": e["breakeven_per_day"],
        "profit": e["profit"], "payback_months": e["payback_months"]}


def _own(s, user_id: str, plan_id: int) -> LaunchPlan | None:
    p = s.get(LaunchPlan, plan_id)
    return p if p is not None and p.active and p.user_id == _uid(user_id) else None


def create(user_id: str, fields: dict, conversation_id: str | None = None) -> dict:
    with SessionLocal() as s:
        p = LaunchPlan(user_id=_uid(user_id), conversation_id=conversation_id, status="ready",
                       **{k: fields[k] for k in ("title", "kind", "city", "area", "answers", "items",
                                                 "assumptions", "benchmarks", "suppliers")})
        s.add(p)
        s.commit()
        s.refresh(p)
        return view(p)


def get(user_id: str, plan_id: int) -> dict | None:
    with SessionLocal() as s:
        p = _own(s, user_id, plan_id)
        return view(p) if p is not None else None


def list_for(user_id: str) -> list[dict]:
    with SessionLocal() as s:
        rows = s.execute(select(LaunchPlan).where(LaunchPlan.user_id == _uid(user_id), LaunchPlan.active.is_(True))
                         .order_by(LaunchPlan.created_at.desc(), LaunchPlan.id.desc()).limit(LIST_LIMIT)).scalars()
        return [summary(p) for p in rows]


UPDATABLE = ("items", "assumptions", "benchmarks", "suppliers", "status", "progress", "error", "title")


def update(user_id: str, plan_id: int, **fields) -> dict | None:
    with SessionLocal() as s:
        p = _own(s, user_id, plan_id)
        if p is None:
            return None
        for k, v in fields.items():
            if k in UPDATABLE:
                setattr(p, k, v)
        p.updated_at = datetime.now(UTC)
        s.commit()
        s.refresh(p)
        return view(p)


def hide(user_id: str, plan_id: int) -> bool:
    with SessionLocal() as s:
        p = _own(s, user_id, plan_id)
        if p is None:
            return False
        p.active = False
        s.commit()
        return True


def month_start(now: datetime | None = None) -> datetime:
    n = now or datetime.now(UTC)
    return n.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def sourced_this_month(user_id: str) -> int:
    """Sourced plans started since the 1st (UTC), hidden ones included: hiding
    a plan doesn't give the search back."""
    with SessionLocal() as s:
        return s.execute(select(func.count(LaunchPlan.id)).where(
            LaunchPlan.user_id == _uid(user_id), LaunchPlan.sourced.is_(True),
            LaunchPlan.sourced_at >= month_start())).scalar_one()


def start_sourcing(user_id: str, plan_id: int, total: int) -> dict | None:
    """Mark the plan as being sourced (counts against the month). None when it
    isn't the user's, or is already being sourced."""
    with SessionLocal() as s:
        p = _own(s, user_id, plan_id)
        if p is None or _status(p)[0] == "sourcing":
            return None
        if not p.sourced:
            p.sourced, p.sourced_at = True, datetime.now(UTC)
        p.status, p.error = "sourcing", ""
        p.progress = {"stage": "prices", "done": 0, "total": total}
        p.updated_at = datetime.now(UTC)
        s.commit()
        s.refresh(p)
        return view(p)


def add_cost(user_id: str, plan_id: int, usd: Decimal) -> None:
    with SessionLocal() as s:
        p = s.get(LaunchPlan, plan_id)
        if p is not None and p.user_id == _uid(user_id):
            p.cost_usd = (p.cost_usd or Decimal(0)) + usd
            s.commit()


def use_refresh(user_id: str, plan_id: int, limit: int) -> bool:
    """Count one item refresh; False once the plan has used ``limit``."""
    with SessionLocal() as s:
        p = _own(s, user_id, plan_id)
        if p is None or (p.refreshes or 0) >= limit:
            return False
        p.refreshes = (p.refreshes or 0) + 1
        s.commit()
        return True
