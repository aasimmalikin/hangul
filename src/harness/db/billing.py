"""A user's billing account: the plan columns on ``users``, written only by
the payment webhook, and the event table that makes it idempotent."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from harness.db.base import SessionLocal
from harness.db.models import BillingEvent, User

_FIELDS = ("plan", "plan_status", "plan_period_start", "plan_renews_at", "plan_ends_at",
           "billing_customer_id", "billing_subscription_id", "plan_region", "plan_interval")


@dataclass
class Account:
    user_id: str
    plan: str = "free"
    plan_status: str | None = None
    plan_period_start: datetime | None = None
    plan_renews_at: datetime | None = None
    plan_ends_at: datetime | None = None
    billing_customer_id: str | None = None
    billing_subscription_id: str | None = None
    plan_region: str = "intl"          # "in" = bought at Indian prices
    plan_interval: str = "month"       # "year" = yearly plan, allowance still monthly


def _uid(user_id: str) -> int | None:
    # users.id is an integer and the JWT `sub` is its string form; anything
    # else (a service token, a test subject) simply has no account row.
    try:
        return int(user_id)
    except (TypeError, ValueError):
        return None


def get_account(user_id: str) -> Account:
    uid = _uid(user_id)
    if uid is None:
        return Account(user_id=user_id)
    with SessionLocal() as s:
        u = s.get(User, uid)
        if u is None:
            return Account(user_id=user_id)
        return Account(user_id=user_id, **{f: getattr(u, f) for f in _FIELDS})


def update_account(user_id: str, **fields) -> bool:
    unknown = set(fields) - set(_FIELDS)
    if unknown:
        raise ValueError(f"not billing fields: {sorted(unknown)}")
    uid = _uid(user_id)
    if uid is None:
        return False
    with SessionLocal() as s:
        u = s.get(User, uid)
        if u is None:
            return False
        for k, v in fields.items():
            setattr(u, k, v)
        s.commit()
        return True


def user_for(*, subscription_id: str | None = None, customer_id: str | None = None,
             email: str | None = None) -> str | None:
    """The user a webhook is about, when it carries no user_id: by the
    subscription or customer already linked, else by verified email."""
    with SessionLocal() as s:
        for col, value in ((User.billing_subscription_id, subscription_id),
                           (User.billing_customer_id, customer_id)):
            if value:
                uid = s.execute(select(User.id).where(col == str(value))).scalar()
                if uid is not None:
                    return str(uid)
        if email:
            uid = s.execute(select(User.id).where(func.lower(User.email) == email.strip().lower())).scalar()
            if uid is not None:
                return str(uid)
    return None


def claim_event(event_id: str, event_name: str) -> bool:
    """True the first time an event is seen, False for a redelivery."""
    with SessionLocal() as s:
        s.add(BillingEvent(id=event_id, event_name=event_name))
        try:
            s.commit()
        except IntegrityError:
            s.rollback()
            return False
        return True


def release_event(event_id: str) -> None:
    """Forget an event whose handling failed, so the provider's retry is applied."""
    with SessionLocal() as s:
        row = s.get(BillingEvent, event_id)
        if row is not None:
            s.delete(row)
            s.commit()


def record_churn(user_id: str, *, plan: str, reason: str, detail: str, outcome: str) -> None:
    from harness.db.models import ChurnFeedback
    uid = _uid(user_id)
    if uid is None:
        return
    with SessionLocal() as s:
        s.add(ChurnFeedback(user_id=uid, plan=plan, reason=reason[:32], detail=(detail or "")[:1000], outcome=outcome))
        s.commit()


def churn_summary(days: int = 90) -> dict:
    """Counts by reason and by outcome over the last ``days``, plus recent comments."""
    from datetime import UTC, timedelta
    from sqlalchemy import func as sfunc
    from harness.db.models import ChurnFeedback
    since = datetime.now(UTC) - timedelta(days=days)
    with SessionLocal() as s:
        q = select(ChurnFeedback.reason, ChurnFeedback.outcome, sfunc.count()).where(ChurnFeedback.created_at >= since) \
            .group_by(ChurnFeedback.reason, ChurnFeedback.outcome)
        rows = s.execute(q).all()
        recent = s.execute(select(ChurnFeedback).where(ChurnFeedback.created_at >= since, ChurnFeedback.detail != "")
                           .order_by(ChurnFeedback.created_at.desc()).limit(20)).scalars().all()
    by_reason: dict[str, dict[str, int]] = {}
    outcomes: dict[str, int] = {}
    for reason, outcome, n in rows:
        by_reason.setdefault(reason, {})[outcome] = n
        outcomes[outcome] = outcomes.get(outcome, 0) + n
    total = sum(outcomes.values())
    saved = outcomes.get("kept", 0) + outcomes.get("downgraded", 0)
    return {"days": days, "total": total, "outcomes": outcomes, "saved_rate": round(saved / total, 3) if total else None,
            "by_reason": by_reason,
            "comments": [{"reason": r.reason, "outcome": r.outcome, "plan": r.plan, "detail": r.detail,
                          "at": r.created_at.isoformat() if r.created_at else None} for r in recent]}
