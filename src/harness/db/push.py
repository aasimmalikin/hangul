"""Push subscriptions: which browsers and installed apps get a user's
notifications (harness/push.py)."""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, func, select, update

from harness.db.base import SessionLocal
from harness.db.models import PushSubscription

MAX_PER_USER = 10            # phones, laptops, browsers; the oldest goes first


@dataclass
class Device:
    endpoint: str
    p256dh: str
    auth: str

    def info(self) -> dict:
        """The shape pywebpush expects (the browser's PushSubscription.toJSON())."""
        return {"endpoint": self.endpoint, "keys": {"p256dh": self.p256dh, "auth": self.auth}}


def save(user_id: str, endpoint: str, p256dh: str, auth: str, user_agent: str | None = None) -> None:
    """Add a device, or refresh its keys. A device already held by another user
    moves to this one: whoever signed in on it last gets its notifications."""
    with SessionLocal() as s:
        row = s.execute(select(PushSubscription).where(PushSubscription.endpoint == endpoint)).scalar_one_or_none()
        if row is None:
            row = PushSubscription(endpoint=endpoint)
            s.add(row)
        row.user_id, row.p256dh, row.auth = int(user_id), p256dh, auth
        row.user_agent = (user_agent or "")[:200] or None
        s.flush()
        extra = s.execute(select(PushSubscription.id).where(PushSubscription.user_id == int(user_id))
                          .order_by(PushSubscription.created_at.desc(), PushSubscription.id.desc())
                          .offset(MAX_PER_USER)).scalars().all()
        if extra:
            s.execute(delete(PushSubscription).where(PushSubscription.id.in_(extra)))
        s.commit()


def remove(user_id: str, endpoint: str) -> bool:
    """This user turns notifications off on one device."""
    with SessionLocal() as s:
        n = s.execute(delete(PushSubscription).where(PushSubscription.user_id == int(user_id),
                                                     PushSubscription.endpoint == endpoint)).rowcount
        s.commit()
        return bool(n)


def forget(endpoint: str) -> None:
    """The push service says the device is gone (unsubscribed, app removed)."""
    with SessionLocal() as s:
        s.execute(delete(PushSubscription).where(PushSubscription.endpoint == endpoint))
        s.commit()


def devices(user_id: str) -> list[Device]:
    with SessionLocal() as s:
        rows = s.execute(select(PushSubscription).where(PushSubscription.user_id == int(user_id))).scalars().all()
        return [Device(r.endpoint, r.p256dh, r.auth) for r in rows]


def count(user_id: str) -> int:
    with SessionLocal() as s:
        return s.execute(select(func.count()).select_from(PushSubscription)
                         .where(PushSubscription.user_id == int(user_id))).scalar_one()


def has(user_id: str, endpoint: str) -> bool:
    with SessionLocal() as s:
        return s.execute(select(PushSubscription.id).where(PushSubscription.user_id == int(user_id),
                                                           PushSubscription.endpoint == endpoint)).first() is not None


def mark_sent(endpoint: str) -> None:
    with SessionLocal() as s:
        s.execute(update(PushSubscription).where(PushSubscription.endpoint == endpoint)
                  .values(last_sent_at=datetime.now(UTC)))
        s.commit()
