"""Google OAuth tokens for the Workspace bundle.

The user signs in with Google (Auth.js); when they connect the bundle they
grant the Workspace scopes and Auth.js stores the refresh token on their
``accounts`` row. This module turns that refresh token into an access token
for the official Google Workspace MCP servers, caching it until it expires.
Access tokens are registered with the vault redactor so they never appear
in logs or answers."""

import asyncio
import time
from dataclasses import dataclass

import httpx
from sqlalchemy import select

from harness.config import get_settings
from harness.db.base import SessionLocal
from harness.db.models import Account
from harness.logging import log
from harness.vault.redact import redactor

TOKEN_URL = "https://oauth2.googleapis.com/token"

# the scopes the bundle needs, per product (read + the writes users expect)
WORKSPACE_SCOPES: dict[str, tuple[str, ...]] = {
    "gmail": ("https://www.googleapis.com/auth/gmail.readonly", "https://www.googleapis.com/auth/gmail.compose"),
    "calendar": ("https://www.googleapis.com/auth/calendar",),
    "drive": ("https://www.googleapis.com/auth/drive.readonly", "https://www.googleapis.com/auth/drive.file"),
    "docs": ("https://www.googleapis.com/auth/documents",),
}
ALL_SCOPES: tuple[str, ...] = tuple(s for ss in WORKSPACE_SCOPES.values() for s in ss)


class GoogleNotConnected(Exception):
    """No Google account with Workspace scopes for this user."""


@dataclass
class GoogleGrant:
    refresh_token: str
    scopes: set[str]
    email: str | None = None


def _load_grant(user_id: str) -> GoogleGrant | None:
    with SessionLocal() as s:
        row = s.execute(select(Account).where(Account.userId == int(user_id), Account.provider == "google")
                        .order_by(Account.id.desc())).scalars().first()
        if row is None or not row.refresh_token:
            return None
        return GoogleGrant(refresh_token=row.refresh_token, scopes=set((row.scope or "").split()))


def connected_products(grant: GoogleGrant | None) -> list[str]:
    if grant is None:
        return []
    return [p for p, needed in WORKSPACE_SCOPES.items() if all(sc in grant.scopes for sc in needed)]


class GoogleTokenSource:
    """user id -> Google access token (refreshed on demand, cached per user)."""

    def __init__(self, http: httpx.AsyncClient | None = None) -> None:
        self._http = http
        self._cache: dict[str, tuple[str, float, list[str]]] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def status(self, user_id: str) -> dict:
        grant = await asyncio.to_thread(_load_grant, user_id)
        return {"connected": grant is not None, "products": connected_products(grant)}

    def _cached(self, user_id: str, product: str | None) -> str | None:
        cached = self._cache.get(user_id)
        if not cached or cached[1] - time.time() <= 60:
            return None
        if product and product not in cached[2]:
            raise GoogleNotConnected(f"Google {product} scopes were not granted; reconnect Google Workspace")
        return cached[0]

    async def access_token(self, user_id: str, *, product: str | None = None) -> str:
        tok = self._cached(user_id, product)
        if tok:
            return tok
        lock = self._locks.setdefault(user_id, asyncio.Lock())
        async with lock:
            tok = self._cached(user_id, product)
            if tok:
                return tok
            grant = await asyncio.to_thread(_load_grant, user_id)
            if grant is None:
                raise GoogleNotConnected("Google Workspace is not connected for this account")
            products = connected_products(grant)
            if product and product not in products:
                raise GoogleNotConnected(f"Google {product} scopes were not granted; reconnect Google Workspace")
            token, ttl = await self._refresh(grant.refresh_token)
            self._cache[user_id] = (token, time.time() + ttl, products)
            redactor.register(token, "google")
            return token

    async def _refresh(self, refresh_token: str) -> tuple[str, int]:
        s = get_settings()
        if not (s.auth_google_id and s.auth_google_secret):
            raise GoogleNotConnected("AUTH_GOOGLE_ID / AUTH_GOOGLE_SECRET are not configured on the backend")
        data = {"client_id": s.auth_google_id, "client_secret": s.auth_google_secret,
                "refresh_token": refresh_token, "grant_type": "refresh_token"}
        client = self._http or httpx.AsyncClient(timeout=15.0)
        try:
            r = await client.post(TOKEN_URL, data=data)
        finally:
            if self._http is None:
                await client.aclose()
        if r.status_code != 200:
            log.warning("google token refresh failed", status=r.status_code)
            raise GoogleNotConnected("Google refused the refresh token; reconnect Google Workspace")
        body = r.json()
        return body["access_token"], int(body.get("expires_in", 3600))

    def forget(self, user_id: str) -> None:
        self._cache.pop(user_id, None)


_source: GoogleTokenSource | None = None


def google_tokens() -> GoogleTokenSource:
    global _source
    if _source is None:
        _source = GoogleTokenSource()
    return _source


def set_google_tokens(src: GoogleTokenSource | None) -> None:
    global _source
    _source = src
