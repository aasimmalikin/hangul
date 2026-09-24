"""Credential and consent persistence.

Plain records (``CredentialRecord`` / ``ConsentRecord``) cross the boundary so
the rest of the vault never touches an ORM row -- and so tests can use the
in-memory stores. ``user_id`` arrives as the JWT ``sub`` (a string); the
column is ``users.id`` (int), so every query casts at this boundary like
``db/memory.py`` does. ``None`` is a system (operator) credential."""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from harness.db.base import SessionLocal
from harness.db.models import VaultConsent, VaultCredential


def _uid(user_id: str | int | None) -> int | None:
    return None if user_id is None or user_id == "system" else int(user_id)


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass
class CredentialRecord:
    id: int
    user_id: int | None
    provider: str
    label: str
    kind: str
    ciphertext: str
    fingerprint: str
    scopes: list = field(default_factory=list)
    created_at: datetime | None = None
    expires_at: datetime | None = None
    revoked_at: datetime | None = None

    @property
    def is_system(self) -> bool:
        return self.user_id is None

    @property
    def usable(self) -> bool:
        if self.revoked_at is not None:
            return False
        return self.expires_at is None or self.expires_at > _now()

    def public(self) -> dict:
        """What the API may show: never ciphertext."""
        return {
            "id": self.id, "provider": self.provider, "label": self.label, "kind": self.kind,
            "fingerprint": self.fingerprint, "scopes": list(self.scopes), "system": self.is_system,
            "created_at": self.created_at, "expires_at": self.expires_at,
            "revoked_at": self.revoked_at,
        }


@dataclass
class ConsentRecord:
    id: int
    user_id: int
    provider: str
    credential_id: int | None
    allow_write: bool
    granted_at: datetime | None
    expires_at: datetime
    revoked_at: datetime | None = None

    @property
    def active(self) -> bool:
        return self.revoked_at is None and self.expires_at > _now()

    def public(self) -> dict:
        return {
            "id": self.id, "provider": self.provider, "credential_id": self.credential_id,
            "allow_write": self.allow_write, "granted_at": self.granted_at,
            "expires_at": self.expires_at, "revoked_at": self.revoked_at,
        }


def _cred(row: VaultCredential) -> CredentialRecord:
    return CredentialRecord(
        id=row.id, user_id=row.user_id, provider=row.provider, label=row.label, kind=row.kind,
        ciphertext=row.ciphertext, fingerprint=row.fingerprint, scopes=list(row.scopes or []),
        created_at=row.created_at, expires_at=row.expires_at, revoked_at=row.revoked_at,
    )


def _consent(row: VaultConsent) -> ConsentRecord:
    return ConsentRecord(
        id=row.id, user_id=row.user_id, provider=row.provider, credential_id=row.credential_id,
        allow_write=row.allow_write, granted_at=row.granted_at, expires_at=row.expires_at,
        revoked_at=row.revoked_at,
    )


class CredentialStore:
    """Postgres-backed. All methods are synchronous; callers use asyncio.to_thread."""

    def add(self, *, user_id: str | None, provider: str, label: str, kind: str, ciphertext: str,
            fingerprint: str, scopes: list | None = None, expires_at: datetime | None = None) -> CredentialRecord:
        with SessionLocal() as s:
            row = VaultCredential(user_id=_uid(user_id), provider=provider, label=label, kind=kind,
                                  ciphertext=ciphertext, fingerprint=fingerprint, scopes=scopes or [],
                                  expires_at=expires_at)
            s.add(row)
            s.commit()
            s.refresh(row)
            return _cred(row)

    def get(self, credential_id: int) -> CredentialRecord | None:
        with SessionLocal() as s:
            row = s.get(VaultCredential, credential_id)
            return _cred(row) if row else None

    def list_for_user(self, user_id: str | None, include_revoked: bool = False) -> list[CredentialRecord]:
        with SessionLocal() as s:
            q = select(VaultCredential).where(VaultCredential.user_id == _uid(user_id))
            if not include_revoked:
                q = q.where(VaultCredential.revoked_at.is_(None))
            rows = s.execute(q.order_by(VaultCredential.created_at.desc())).scalars().all()
            return [_cred(r) for r in rows]

    def find(self, user_id: str | None, provider: str) -> CredentialRecord | None:
        """Newest usable credential for (user, provider); user None = system."""
        for c in self.list_for_user(user_id):
            if c.provider == provider and c.usable:
                return c
        return None

    def find_by_fingerprint(self, user_id: str | None, provider: str, fingerprint: str) -> CredentialRecord | None:
        for c in self.list_for_user(user_id):
            if c.provider == provider and c.fingerprint == fingerprint:
                return c
        return None

    def revoke(self, user_id: str | None, credential_id: int) -> bool:
        """False when missing, already revoked, or someone else's -- callers
        answer 404 for all three so ids cannot be probed."""
        with SessionLocal() as s:
            row = s.get(VaultCredential, credential_id)
            if row is None or row.user_id != _uid(user_id) or row.revoked_at is not None:
                return False
            row.revoked_at = _now()
            s.commit()
            return True


class ConsentStore:
    def grant(self, *, user_id: str, provider: str, credential_id: int | None, ttl: timedelta,
              allow_write: bool = False) -> ConsentRecord:
        with SessionLocal() as s:
            row = VaultConsent(user_id=_uid(user_id), provider=provider, credential_id=credential_id,
                               allow_write=allow_write, expires_at=_now() + ttl)
            s.add(row)
            s.commit()
            s.refresh(row)
            return _consent(row)

    def list_for_user(self, user_id: str, include_inactive: bool = False) -> list[ConsentRecord]:
        with SessionLocal() as s:
            rows = s.execute(select(VaultConsent).where(VaultConsent.user_id == _uid(user_id))
                             .order_by(VaultConsent.granted_at.desc())).scalars().all()
            out = [_consent(r) for r in rows]
            return out if include_inactive else [c for c in out if c.active]

    def active(self, user_id: str, provider: str) -> ConsentRecord | None:
        for c in self.list_for_user(user_id):
            if c.provider == provider:
                return c
        return None

    def revoke(self, user_id: str, consent_id: int) -> bool:
        with SessionLocal() as s:
            row = s.get(VaultConsent, consent_id)
            if row is None or row.user_id != _uid(user_id) or row.revoked_at is not None:
                return False
            row.revoked_at = _now()
            s.commit()
            return True

    def revoke_for_credential(self, credential_id: int) -> int:
        with SessionLocal() as s:
            rows = s.execute(select(VaultConsent).where(VaultConsent.credential_id == credential_id,
                                                         VaultConsent.revoked_at.is_(None))).scalars().all()
            for r in rows:
                r.revoked_at = _now()
            s.commit()
            return len(rows)


# ------------------------------------------------------------------ in-memory

class InMemoryCredentialStore(CredentialStore):
    def __init__(self) -> None:
        self._rows: dict[int, CredentialRecord] = {}
        self._seq = 0

    def add(self, *, user_id, provider, label, kind, ciphertext, fingerprint, scopes=None, expires_at=None):
        self._seq += 1
        rec = CredentialRecord(id=self._seq, user_id=_uid(user_id), provider=provider, label=label,
                               kind=kind, ciphertext=ciphertext, fingerprint=fingerprint,
                               scopes=list(scopes or []), created_at=_now(), expires_at=expires_at)
        self._rows[rec.id] = rec
        return rec

    def get(self, credential_id):
        return self._rows.get(credential_id)

    def list_for_user(self, user_id, include_revoked=False):
        return [c for c in sorted(self._rows.values(), key=lambda c: -c.id)
                if c.user_id == _uid(user_id) and (include_revoked or c.revoked_at is None)]

    def revoke(self, user_id, credential_id):
        c = self._rows.get(credential_id)
        if c is None or c.user_id != _uid(user_id) or c.revoked_at is not None:
            return False
        c.revoked_at = _now()
        return True


class InMemoryConsentStore(ConsentStore):
    def __init__(self) -> None:
        self._rows: dict[int, ConsentRecord] = {}
        self._seq = 0

    def grant(self, *, user_id, provider, credential_id, ttl, allow_write=False):
        self._seq += 1
        rec = ConsentRecord(id=self._seq, user_id=_uid(user_id), provider=provider,
                            credential_id=credential_id, allow_write=allow_write,
                            granted_at=_now(), expires_at=_now() + ttl)
        self._rows[rec.id] = rec
        return rec

    def list_for_user(self, user_id, include_inactive=False):
        out = [c for c in sorted(self._rows.values(), key=lambda c: -c.id) if c.user_id == _uid(user_id)]
        return out if include_inactive else [c for c in out if c.active]

    def revoke(self, user_id, consent_id):
        c = self._rows.get(consent_id)
        if c is None or c.user_id != _uid(user_id) or c.revoked_at is not None:
            return False
        c.revoked_at = _now()
        return True

    def revoke_for_credential(self, credential_id):
        hit = [c for c in self._rows.values() if c.credential_id == credential_id and c.revoked_at is None]
        for c in hit:
            c.revoked_at = _now()
        return len(hit)
