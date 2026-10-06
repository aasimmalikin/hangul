"""WhatsApp links: which number belongs to which user, the linking code, the
WhatsApp conversation, and the 24-hour window (harness/whatsapp)."""

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from harness.db.base import SessionLocal
from harness.db.models import WhatsAppInbound, WhatsAppLink

WINDOW = timedelta(hours=24)      # Meta: free-form replies only within 24 h of the user's last message


@dataclass
class Link:
    user_id: str
    phone: str | None
    linked: bool
    conversation_id: str | None
    last_inbound_at: datetime | None
    pending_text: str | None

    def window_open(self, now: datetime | None = None) -> bool:
        if self.last_inbound_at is None:
            return False
        last = self.last_inbound_at if self.last_inbound_at.tzinfo else self.last_inbound_at.replace(tzinfo=UTC)
        return (now or datetime.now(UTC)) - last < WINDOW


def _to(row: WhatsAppLink | None) -> Link | None:
    if row is None:
        return None
    return Link(user_id=str(row.user_id), phone=row.phone, linked=row.linked_at is not None and bool(row.phone),
                conversation_id=row.conversation_id, last_inbound_at=row.last_inbound_at, pending_text=row.pending_text)


def _hash(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def start_link(user_id: str, ttl_s: int) -> str:
    """A fresh 6-digit code for this user (only its hash is stored). Sending it
    from WhatsApp links the sender's number."""
    with SessionLocal() as s:
        row = s.get(WhatsAppLink, int(user_id))
        if row is None:
            row = WhatsAppLink(user_id=int(user_id))
            s.add(row)
        now = datetime.now(UTC)
        for _ in range(10):                # avoid a code another user is holding right now
            code = f"{secrets.randbelow(1_000_000):06d}"
            clash = s.execute(select(WhatsAppLink).where(WhatsAppLink.link_code_hash == _hash(code),
                                                         WhatsAppLink.link_code_expires_at > now,
                                                         WhatsAppLink.user_id != int(user_id))).first()
            if clash is None:
                break
        row.link_code_hash = _hash(code)
        row.link_code_expires_at = now + timedelta(seconds=ttl_s)
        s.commit()
        return code


def claim_code(code: str, phone: str) -> str | None:
    """Link ``phone`` to whoever holds this unexpired code; the user id, or None.
    A number belongs to one account: it is taken off any other first."""
    now = datetime.now(UTC)
    with SessionLocal() as s:
        row = s.execute(select(WhatsAppLink).where(WhatsAppLink.link_code_hash == _hash(code),
                                                   WhatsAppLink.link_code_expires_at > now)).scalars().first()
        if row is None:
            return None
        for other in s.execute(select(WhatsAppLink).where(WhatsAppLink.phone == phone,
                                                          WhatsAppLink.user_id != row.user_id)).scalars():
            other.phone, other.linked_at, other.conversation_id = None, None, None
        s.flush()
        row.phone, row.linked_at, row.last_inbound_at = phone, now, now
        row.link_code_hash, row.link_code_expires_at = None, None
        s.commit()
        return str(row.user_id)


def by_phone(phone: str) -> Link | None:
    with SessionLocal() as s:
        return _to(s.execute(select(WhatsAppLink).where(WhatsAppLink.phone == phone)).scalars().first())


def by_user(user_id: str) -> Link | None:
    with SessionLocal() as s:
        return _to(s.get(WhatsAppLink, int(user_id)))


def unlink(user_id: str) -> bool:
    with SessionLocal() as s:
        row = s.get(WhatsAppLink, int(user_id))
        if row is None or not row.phone:
            return False
        row.phone = row.linked_at = row.conversation_id = row.last_inbound_at = row.pending_text = None
        row.link_code_hash = row.link_code_expires_at = None
        s.commit()
        return True


def update(user_id: str, **fields) -> None:
    """Set conversation_id, last_inbound_at or pending_text."""
    allowed = {"conversation_id", "last_inbound_at", "pending_text"}
    if set(fields) - allowed:
        raise ValueError(f"not whatsapp link fields: {sorted(set(fields) - allowed)}")
    with SessionLocal() as s:
        row = s.get(WhatsAppLink, int(user_id))
        if row is None:
            return
        for k, v in fields.items():
            setattr(row, k, v)
        s.commit()


def first_time(wamid: str) -> bool:
    """True the first time a message id is seen (Meta retries deliveries)."""
    with SessionLocal() as s:
        s.add(WhatsAppInbound(wamid=wamid[:128]))
        try:
            s.commit()
            return True
        except IntegrityError:
            s.rollback()
            return False
