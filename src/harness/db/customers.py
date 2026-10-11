"""A shop's own customer list: the regulars, their phones and birthdays, and how
often they come in. Owned by the user (the business owner); a foreign id behaves
exactly like a missing one (None -> 404). Hidden, not deleted.

Adding someone who is already on the list (same phone, or the same name when
neither has a phone) fills in what's new instead of making a duplicate, so the
chat can say "add Riya, 98xxxxxxx" twice without harm.
"""

import re
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, or_, select

from harness.db.base import SessionLocal
from harness.db.models import Customer
from harness.provenance import stamp

MAX_PER_USER = 5000
EDITABLE = ("name", "phone", "birthday", "note", "business_id")
MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august", "september",
          "october", "november", "december")


class TooMany(Exception):
    pass


def _uid(user_id: str) -> int:
    return int(user_id)


# ------------------------------------------------------------ parsing

def normalise_phone(raw: str | None) -> str:
    """'98765 43210' / '+91-98765-43210' / '098765 43210' -> '+919876543210'; '' when empty.
    Raises ValueError for something that can't be a phone number."""
    s = (raw or "").strip()
    if not s:
        return ""
    plus = s.startswith("+")
    digits = re.sub(r"\D", "", s)
    if not plus:
        if len(digits) == 11 and digits.startswith("0"):
            digits = digits[1:]
        if len(digits) == 10:                         # an Indian mobile written without the code
            digits = "91" + digits
    if not 8 <= len(digits) <= 15:
        raise ValueError("phone")
    return "+" + digits


def parse_birthday(raw: str | None) -> tuple[int | None, int, int] | None:
    """(year or None, month, day) from '1990-03-12', '12/03', '12-03-1990', '12 March',
    'March 12' or '12 Mar 1990' (numbers are day first, as written in India). None when
    empty; ValueError when it isn't a real date."""
    s = (raw or "").strip().lower().replace(",", " ")
    if not s:
        return None
    year = month = day = None
    if m := re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", s):
        year, month, day = int(m[1]), int(m[2]), int(m[3])
    elif m := re.fullmatch(r"(\d{1,2})[/.-](\d{1,2})(?:[/.-](\d{4}))?", s):
        day, month, year = int(m[1]), int(m[2]), int(m[3]) if m[3] else None
    else:
        words = s.split()
        nums = [w for w in words if w.isdigit()]
        names = [i + 1 for w in words for i, mo in enumerate(MONTHS) if len(w) >= 3 and mo.startswith(w)]
        if len(names) == 1 and nums:
            month = names[0]
            day = int(next(n for n in nums if len(n) <= 2)) if any(len(n) <= 2 for n in nums) else None
            year = next((int(n) for n in nums if len(n) == 4), None)
    if not (month and day):
        raise ValueError("birthday")
    try:
        date(year or 2000, month, day)                  # 2000 is a leap year, so 29 Feb is fine
    except ValueError as e:
        raise ValueError("birthday") from e
    if year is not None and not 1900 <= year <= datetime.now(UTC).year:
        raise ValueError("birthday")
    return year, month, day


def view(c: Customer) -> dict:
    bday = None
    if c.birth_month and c.birth_day:
        bday = (f"{c.birth_year:04d}-" if c.birth_year else "") + f"{c.birth_month:02d}-{c.birth_day:02d}"
    return {"id": c.id, "name": c.name, "phone": c.phone, "birthday": bday, "note": c.note,
            "visits": c.visits, "last_visit": c.last_visit.isoformat() if c.last_visit else None,
            "business_id": c.business_id}


def _own(s, user_id: str, customer_id: int) -> Customer | None:
    c = s.get(Customer, customer_id)
    return c if c is not None and c.active and c.user_id == _uid(user_id) else None


def _apply(c: Customer, fields: dict) -> None:
    if "name" in fields and (fields["name"] or "").strip():
        c.name = fields["name"].strip()[:80]
    if "phone" in fields and fields["phone"] is not None:
        c.phone = normalise_phone(fields["phone"])
    if "birthday" in fields and fields["birthday"] is not None:
        b = parse_birthday(fields["birthday"])
        c.birth_year, c.birth_month, c.birth_day = b if b else (None, None, None)
    if "note" in fields and fields["note"] is not None:
        c.note = fields["note"].strip()[:200]
    if "business_id" in fields:
        c.business_id = fields["business_id"]


# ------------------------------------------------------------ writes

def add(user_id: str, name: str, phone: str = "", birthday: str = "", note: str = "",
        business_id: int | None = None) -> tuple[dict, bool]:
    """(the customer, True if new). Same phone -- or, with no phone, the same name --
    updates the one already there with what's new."""
    name = (name or "").strip()[:80]
    if not name:
        raise ValueError("name")
    fields = {"name": name, "phone": phone or None, "birthday": birthday or None, "note": note or None}
    norm = normalise_phone(phone)
    parse_birthday(birthday)                            # refuse a bad date before anything is written
    with SessionLocal() as s:
        mine = select(Customer).where(Customer.user_id == _uid(user_id), Customer.active.is_(True))
        hit = None
        if norm:
            hit = s.execute(mine.where(Customer.phone == norm)).scalars().first()
        if hit is None:
            same_name = mine.where(func.lower(Customer.name) == name.lower())
            if norm:                                    # a new number only matches a name with no number yet
                same_name = same_name.where(Customer.phone == "")
            hit = s.execute(same_name).scalars().first()
        if hit is not None:
            _apply(hit, {k: v for k, v in fields.items() if v})
            s.commit()
            return view(hit), False
        if s.execute(select(func.count(Customer.id)).where(Customer.user_id == _uid(user_id),
                                                            Customer.active.is_(True))).scalar_one() >= MAX_PER_USER:
            raise TooMany()
        c = Customer(user_id=_uid(user_id), name=name, business_id=business_id, **stamp())
        _apply(c, fields)
        s.add(c)
        s.commit()
        return view(c), True


def update(user_id: str, customer_id: int, **fields) -> dict | None:
    with SessionLocal() as s:
        c = _own(s, user_id, customer_id)
        if c is None:
            return None
        _apply(c, {k: v for k, v in fields.items() if k in EDITABLE})
        s.commit()
        return view(c)


def remove(user_id: str, customer_id: int) -> bool:
    with SessionLocal() as s:
        c = _own(s, user_id, customer_id)
        if c is None:
            return False
        c.active = False
        s.commit()
        return True


def visit(user_id: str, customer_id: int, day: date) -> dict | None:
    """They came in on ``day``: counted once per day."""
    with SessionLocal() as s:
        c = _own(s, user_id, customer_id)
        if c is None:
            return None
        if c.last_visit != day:
            c.visits = (c.visits or 0) + 1
            c.last_visit = max(day, c.last_visit) if c.last_visit else day
        s.commit()
        return view(c)


# ------------------------------------------------------------ reads

def get(user_id: str, customer_id: int) -> dict | None:
    with SessionLocal() as s:
        c = _own(s, user_id, customer_id)
        return view(c) if c else None


def find(user_id: str, q: str = "", limit: int = 50) -> list[dict]:
    """By name or phone (any part); everyone, most recent visitors first, when ``q`` is empty."""
    with SessionLocal() as s:
        stmt = select(Customer).where(Customer.user_id == _uid(user_id), Customer.active.is_(True))
        q = (q or "").strip()
        if q:
            digits = re.sub(r"\D", "", q)
            conds = [func.lower(Customer.name).contains(q.lower())]
            if len(digits) >= 4:
                conds.append(Customer.phone.contains(digits))
            stmt = stmt.where(or_(*conds))
        stmt = stmt.order_by(Customer.last_visit.desc().nulls_last(), Customer.name).limit(max(1, min(limit, 500)))
        return [view(c) for c in s.execute(stmt).scalars()]


def count(user_id: str) -> int:
    with SessionLocal() as s:
        return s.execute(select(func.count(Customer.id)).where(Customer.user_id == _uid(user_id),
                                                               Customer.active.is_(True))).scalar_one()


def _next_birthday(month: int, day: int, today: date) -> date:
    for year in (today.year, today.year + 1):
        try:
            when = date(year, month, day)
        except ValueError:                              # 29 Feb in a non-leap year
            when = date(year, 2, 28)
        if when >= today:
            return when
    return when


def upcoming_birthdays(user_id: str, today: date, days: int = 7) -> list[dict]:
    """Customers with a birthday within ``days`` of ``today`` (inclusive), soonest first,
    shaped like the Contacts birthdays on Today (plus ``customer`` and ``phone``)."""
    with SessionLocal() as s:
        rows = s.execute(select(Customer).where(Customer.user_id == _uid(user_id), Customer.active.is_(True),
                                                Customer.birth_month.is_not(None))).scalars().all()
    out = []
    for c in rows:
        when = _next_birthday(c.birth_month, c.birth_day, today)
        in_days = (when - today).days
        if in_days <= days:
            item = {"name": c.name, "date": when.isoformat(), "in_days": in_days, "customer": True,
                    "customer_id": c.id, "phone": c.phone}
            if c.birth_year:
                item["turns"] = when.year - c.birth_year
            out.append(item)
    return sorted(out, key=lambda b: (b["in_days"], b["name"]))


def lapsed(user_id: str, today: date, days: int = 30, min_visits: int = 3, limit: int = 20) -> list[dict]:
    """Regulars (``min_visits`` or more) who haven't been in for ``days`` days, longest gap first."""
    since = today - timedelta(days=days)
    with SessionLocal() as s:
        rows = s.execute(select(Customer).where(Customer.user_id == _uid(user_id), Customer.active.is_(True),
                                                Customer.visits >= min_visits, Customer.last_visit < since)
                         .order_by(Customer.last_visit).limit(limit)).scalars().all()
        return [{**view(c), "days_away": (today - c.last_visit).days} for c in rows]
