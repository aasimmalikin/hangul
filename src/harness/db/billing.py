"""A user's billing account: the plan columns on ``users``, written only by
the payment webhook, and the event table that makes it idempotent."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from harness.db.base import SessionLocal
from harness.db.models import BillingEvent, User

_FIELDS = ("plan", "plan_status", "plan_period_start", "plan_renews_at", "plan_ends_at",
           "billing_customer_id", "billing_subscription_id")


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
