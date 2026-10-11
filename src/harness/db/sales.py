"""How's business (harness.sales): the user's businesses, their daily takings
and events. A foreign id behaves exactly like a missing one (None -> 404).

Businesses per plan: ``Plan.businesses_included`` (Free 1, Plus 1, Pro 5;
billing off = BILLING_OFF_SLOTS). Days are unique per business and date: a
second log for the same day replaces it, or adds to it when asked.
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func, select

from harness.db.base import SessionLocal
from harness.db.models import Business, BusinessDay, BusinessEvent

BILLING_OFF_SLOTS = 10
EDITABLE = ("name", "kind", "city", "brand_id", "launch_plan_id", "nudges")


class LimitReached(Exception):
    def __init__(self, slots: int):
        super().__init__(f"Your plan includes {slots} business(es).")
        self.slots = slots


def _uid(user_id: str) -> int:
    return int(user_id)


def biz_view(b: Business) -> dict:
    return {"id": b.id, "name": b.name, "kind": b.kind, "city": b.city, "brand_id": b.brand_id,
            "launch_plan_id": b.launch_plan_id, "nudges": bool(b.nudges),
            "lat": float(b.lat) if b.lat is not None else None, "lon": float(b.lon) if b.lon is not None else None,
            "nudged": list(b.nudged or []), "created_at": b.created_at.isoformat() if b.created_at else None}


def day_view(d: BusinessDay) -> dict:
    return {"day": d.day.isoformat(), "sales": float(d.sales), "bills": d.bills, "closed": bool(d.closed),
            "partial": bool(d.partial), "promo": bool(d.promo), "source": d.source, "note": d.note,
            "rain_mm": float(d.rain_mm) if d.rain_mm is not None else None,
            "tmax": float(d.tmax) if d.tmax is not None else None}


def slots(user_id: str) -> int:
    from harness.billing import entitlements
    from harness.billing.plans import get_plan
    if not entitlements.billing_enabled():
        return BILLING_OFF_SLOTS
    from harness.db import billing as billing_db
    return get_plan(billing_db.get_account(user_id).plan).businesses_included


def _own(s, user_id: str, business_id: int) -> Business | None:
    b = s.get(Business, business_id)
    return b if b is not None and b.active and b.user_id == _uid(user_id) else None


def list_for(user_id: str) -> list[dict]:
    """Oldest first; those past the plan's count are ``paused`` (kept, not usable)."""
    limit = slots(user_id)
    with SessionLocal() as s:
        rows = s.execute(select(Business).where(Business.user_id == _uid(user_id), Business.active.is_(True))
                         .order_by(Business.created_at, Business.id)).scalars().all()
        return [{**biz_view(b), "paused": i >= limit} for i, b in enumerate(rows)]


def get(user_id: str, business_id: int) -> dict | None:
    return next((b for b in list_for(user_id) if b["id"] == business_id), None)


def first(user_id: str) -> dict | None:
    rows = [b for b in list_for(user_id) if not b["paused"]]
    return rows[0] if rows else None


def create(user_id: str, **fields) -> dict:
    limit = slots(user_id)
    with SessionLocal() as s:
        used = s.execute(select(func.count(Business.id)).where(
            Business.user_id == _uid(user_id), Business.active.is_(True))).scalar_one()
        if used >= limit:
            raise LimitReached(limit)
        b = Business(user_id=_uid(user_id), **{k: v for k, v in fields.items() if k in EDITABLE})
        s.add(b)
        s.commit()
        s.refresh(b)
        return {**biz_view(b), "paused": False}


def update(user_id: str, business_id: int, **fields) -> dict | None:
    with SessionLocal() as s:
        b = _own(s, user_id, business_id)
        if b is None:
            return None
        for k, v in fields.items():
            if k in EDITABLE + ("lat", "lon", "nudged"):
                setattr(b, k, v)
        s.commit()
    return get(user_id, business_id)


def hide(user_id: str, business_id: int) -> bool:
    with SessionLocal() as s:
        b = _own(s, user_id, business_id)
        if b is None:
            return False
        b.active = False
        s.commit()
        return True


# ------------------------------------------------------------ days

def log_day(business_id: int, day: date, *, sales: float, bills: int | None = None, closed: bool = False,
            partial: bool = False, promo: bool | None = None, source: str = "chat", note: str = "", add: bool = False) -> dict:
    """Save a day's takings (``add`` adds to what's there instead of replacing it)."""
    with SessionLocal() as s:
        d = s.execute(select(BusinessDay).where(BusinessDay.business_id == business_id, BusinessDay.day == day)).scalar_one_or_none()
        if d is None:
            d = BusinessDay(business_id=business_id, day=day, sales=Decimal(0))
            s.add(d)
        if add and not d.closed:
            d.sales = (d.sales or Decimal(0)) + Decimal(str(round(sales, 2)))
            d.bills = (d.bills or 0) + bills if bills is not None else d.bills
        else:
            d.sales, d.bills = Decimal(str(round(sales, 2))), bills
        d.closed, d.partial, d.source = closed, partial, source
        if promo is not None:
            d.promo = promo
        if note:
            d.note = note[:200]
        d.updated_at = datetime.now().astimezone()
        s.commit()
        s.refresh(d)
        return day_view(d)


def import_days(business_id: int, days: list[dict], *, replace: bool = False) -> dict:
    """Days from a spreadsheet. Days already logged are kept unless ``replace``."""
    added = replaced = kept = 0
    with SessionLocal() as s:
        have = {d.day: d for d in s.execute(select(BusinessDay).where(BusinessDay.business_id == business_id)).scalars()}
        for row in days:
            day = date.fromisoformat(row["day"])
            cur = have.get(day)
            if cur is not None and not replace:
                kept += 1
                continue
            if cur is None:
                cur = BusinessDay(business_id=business_id, day=day)
                s.add(cur)
                added += 1
            else:
                replaced += 1
            cur.sales, cur.bills, cur.closed, cur.partial, cur.source = Decimal(str(row["sales"])), row.get("bills"), False, False, "import"
        s.commit()
    return {"added": added, "replaced": replaced, "kept": kept}


def days_for(business_id: int, since: date | None = None) -> list[dict]:
    with SessionLocal() as s:
        q = select(BusinessDay).where(BusinessDay.business_id == business_id)
        if since:
            q = q.where(BusinessDay.day >= since)
        return [day_view(d) for d in s.execute(q.order_by(BusinessDay.day)).scalars()]


def delete_day(business_id: int, day: date) -> bool:
    with SessionLocal() as s:
        d = s.execute(select(BusinessDay).where(BusinessDay.business_id == business_id, BusinessDay.day == day)).scalar_one_or_none()
        if d is None:
            return False
        s.delete(d)
        s.commit()
        return True


def set_weather(business_id: int, weather: dict[date, tuple[float | None, float | None]]) -> int:
    n = 0
    with SessionLocal() as s:
        for d in s.execute(select(BusinessDay).where(BusinessDay.business_id == business_id,
                                                     BusinessDay.day.in_(list(weather)))).scalars():
            rain, tmax = weather[d.day]
            if rain is not None:
                d.rain_mm, d.tmax, n = Decimal(str(round(rain, 1))), (Decimal(str(round(tmax, 1))) if tmax is not None else None), n + 1
        s.commit()
    return n


# ------------------------------------------------------------ events

def add_event(business_id: int, day: date, kind: str, detail: dict | None = None) -> None:
    with SessionLocal() as s:
        s.add(BusinessEvent(business_id=business_id, day=day, kind=kind, detail=detail or {}))
        s.commit()


def events(business_id: int, kind: str, since: date) -> list[dict]:
    with SessionLocal() as s:
        rows = s.execute(select(BusinessEvent).where(BusinessEvent.business_id == business_id, BusinessEvent.kind == kind,
                                                     BusinessEvent.day >= since).order_by(BusinessEvent.day)).scalars()
        return [{"day": e.day.isoformat(), "kind": e.kind, "detail": e.detail or {}} for e in rows]


def remove_events(business_id: int, day: date, kind: str, key: str) -> int:
    """Take back the events a suggestion added (a mission the owner undid)."""
    with SessionLocal() as s:
        rows = [e for e in s.execute(select(BusinessEvent).where(
            BusinessEvent.business_id == business_id, BusinessEvent.day == day, BusinessEvent.kind == kind)).scalars()
            if (e.detail or {}).get("key") == key]
        for e in rows:
            s.delete(e)
        s.commit()
        return len(rows)
