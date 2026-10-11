"""Pre-registration before launch: the /join page's list.

An email is added once (lower-cased); joining again only fills in the trade (the
kind of business), city, persona or plan interest if they were blank, and is
otherwise a no-op. The trade is the traction signal: who is signing up, by business. Callers get the same
answer either way, so the public endpoint never reveals whether an address was
already on the list.

Export for launch day (e.g. to email founding members):

    python -m harness.db.waitlist export > waitlist.csv
"""

import csv
import re
import sys
from datetime import UTC

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from harness.db.settings import PERSONAS

INTERESTS = ("free", "plus", "pro")
# the kinds of business (launch/kinds.py + "other"; the web's BUSINESS_KINDS)
TRADES = ("retail_shop", "cafe", "cloud_kitchen", "salon", "d2c_brand", "other")
# Deliberately simple: one @, a dot in the domain, no spaces. The real check is
# the email we send at launch.
_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,189}\.[^@\s]{2,63}$")
_SOURCE = re.compile(r"[^a-z0-9_.-]")


def normalise_email(email: str) -> str | None:
    e = (email or "").strip().lower()
    return e if len(e) <= 254 and _EMAIL.match(e) else None


def clean_source(source: str | None) -> str:
    return _SOURCE.sub("", (source or "").strip().lower())[:40]


def join(email: str, persona: str = "", interest: str = "", source: str = "", trade: str = "", city: str = "") -> None:
    """Add an email to the list (idempotent). Raises ValueError on bad input."""
    from harness.db.base import SessionLocal
    from harness.db.models import WaitlistEntry
    e = normalise_email(email)
    if e is None:
        raise ValueError("email")
    if persona and persona not in PERSONAS:
        raise ValueError("persona")
    if interest and interest not in INTERESTS:
        raise ValueError("interest")
    if trade and trade not in TRADES:
        raise ValueError("trade")
    city = " ".join((city or "").split())[:80]
    with SessionLocal() as s:
        row = s.execute(select(WaitlistEntry).where(WaitlistEntry.email == e)).scalar_one_or_none()
        if row is None:
            s.add(WaitlistEntry(email=e, persona=persona, interest=interest, source=clean_source(source),
                                trade=trade, city=city))
            try:
                s.commit()
            except IntegrityError:  # the same address joined twice at once: one row is enough
                s.rollback()
            return
        row.persona = row.persona or persona
        row.interest = row.interest or interest
        row.trade = row.trade or trade
        row.city = row.city or city
        s.commit()


def total() -> int:
    from harness.db.base import SessionLocal
    from harness.db.models import WaitlistEntry
    with SessionLocal() as s:
        return s.execute(select(func.count(WaitlistEntry.id))).scalar_one()


def summary() -> dict:
    """Counts for the operator (/admin/waitlist): total, last 7 days, by trade, city (top 10),
    persona, plan and source."""
    from datetime import datetime, timedelta

    from harness.db.base import SessionLocal
    from harness.db.models import WaitlistEntry
    since = datetime.now(UTC) - timedelta(days=7)
    with SessionLocal() as s:
        def by(col) -> dict[str, int]:
            return {k or "unknown": n for k, n in s.execute(select(col, func.count(WaitlistEntry.id)).group_by(col)).all()}
        return {
            "total": s.execute(select(func.count(WaitlistEntry.id))).scalar_one(),
            "last_7_days": s.execute(select(func.count(WaitlistEntry.id)).where(WaitlistEntry.created_at >= since)).scalar_one(),
            "by_trade": by(WaitlistEntry.trade),
            "by_city": dict(sorted(by(func.lower(WaitlistEntry.city)).items(), key=lambda kv: -kv[1])[:10]),
            "by_persona": by(WaitlistEntry.persona),
            "by_interest": by(WaitlistEntry.interest),
            "by_source": by(WaitlistEntry.source),
        }


def export(out=sys.stdout) -> int:
    """Write the list as CSV, oldest first. Returns the number of rows."""
    from harness.db.base import SessionLocal
    from harness.db.models import WaitlistEntry
    w = csv.writer(out)
    w.writerow(["email", "trade", "city", "persona", "interest", "source", "joined_at"])
    with SessionLocal() as s:
        rows = s.execute(select(WaitlistEntry).order_by(WaitlistEntry.id)).scalars().all()
        for r in rows:
            w.writerow([r.email, r.trade, r.city, r.persona, r.interest, r.source,
                        r.created_at.isoformat() if r.created_at else ""])
    return len(rows)


if __name__ == "__main__":
    if sys.argv[1:] != ["export"]:
        sys.exit("usage: python -m harness.db.waitlist export > waitlist.csv")
    n = export()
    print(f"{n} rows", file=sys.stderr)
