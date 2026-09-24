"""Short-lived grants: the only thing the agent's tools and MCP servers ever
hold. Opaque random tokens; only the SHA-256 of a token is stored, with the
scope and a TTL. Redis is the store because expiry is native there."""

import hashlib
import json
import secrets
import time
from dataclasses import asdict, dataclass

from redis.asyncio import Redis
from redis.exceptions import RedisError

from harness.vault.policy import GrantScope

PREFIX = "vg_"
KEY = "vault:grant:"


class GrantError(Exception):
    """Invalid, expired, exhausted or revoked grant."""


@dataclass
class Grant:
    credential_id: int
    scope: GrantScope
    calls_left: int
    expires_at: float
    token_hash: str

    def as_json(self) -> str:
        d = asdict(self)
        d["scope"] = asdict(self.scope)
        return json.dumps(d)

    @classmethod
    def from_json(cls, s: str) -> "Grant":
        d = json.loads(s)
        d["scope"] = GrantScope(**d["scope"])
        return cls(**d)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_token() -> str:
    return PREFIX + secrets.token_urlsafe(32)


class GrantStore:
    """Interface + Redis implementation. ``InMemoryGrantStore`` below is for
    tests and for running without Redis."""

    def __init__(self, redis: Redis) -> None:
        self._r = redis

    async def mint(self, credential_id: int, scope: GrantScope, *, ttl_s: int, max_calls: int) -> tuple[str, Grant]:
        token = new_token()
        grant = Grant(credential_id=credential_id, scope=scope, calls_left=max_calls,
                      expires_at=time.time() + ttl_s, token_hash=_hash(token))
        try:
            await self._r.set(KEY + grant.token_hash, grant.as_json(), ex=ttl_s)
        except RedisError as e:
            raise GrantError(f"grant store unavailable: {type(e).__name__}") from e
        return token, grant

    async def lookup(self, token: str) -> Grant:
        if not token or not token.startswith(PREFIX):
            raise GrantError("malformed grant")
        try:
            raw = await self._r.get(KEY + _hash(token))
        except RedisError as e:
            raise GrantError(f"grant store unavailable: {type(e).__name__}") from e
        if raw is None:
            raise GrantError("unknown, expired or revoked grant")
        grant = Grant.from_json(raw)
        if grant.expires_at < time.time():
            raise GrantError("grant expired")
        return grant

    async def consume(self, grant: Grant) -> Grant:
        """Spend one call. Atomic on the stored JSON via WATCH/MULTI."""
        key = KEY + grant.token_hash
        try:
            async with self._r.pipeline(transaction=True) as pipe:
                await pipe.watch(key)
                raw = await pipe.get(key)
                if raw is None:
                    raise GrantError("unknown, expired or revoked grant")
                current = Grant.from_json(raw)
                if current.calls_left <= 0:
                    raise GrantError("grant call budget exhausted")
                current.calls_left -= 1
                ttl = max(1, int(current.expires_at - time.time()))
                pipe.multi()
                await pipe.set(key, current.as_json(), ex=ttl)
                await pipe.execute()
                return current
        except RedisError as e:
            raise GrantError(f"grant store unavailable: {type(e).__name__}") from e

    async def revoke(self, token: str) -> None:
        try:
            await self._r.delete(KEY + _hash(token))
        except RedisError:
            pass

    async def revoke_credential(self, credential_id: int) -> int:
        """Drop every live grant for a credential (on credential revoke)."""
        n = 0
        try:
            async for key in self._r.scan_iter(match=KEY + "*"):
                raw = await self._r.get(key)
                if raw and Grant.from_json(raw).credential_id == credential_id:
                    await self._r.delete(key)
                    n += 1
        except RedisError:
            pass
        return n


class InMemoryGrantStore(GrantStore):
    def __init__(self) -> None:
        self._d: dict[str, Grant] = {}

    async def mint(self, credential_id, scope, *, ttl_s, max_calls):
        token = new_token()
        grant = Grant(credential_id=credential_id, scope=scope, calls_left=max_calls,
                      expires_at=time.time() + ttl_s, token_hash=_hash(token))
        self._d[grant.token_hash] = grant
        return token, grant

    async def lookup(self, token):
        if not token or not token.startswith(PREFIX):
            raise GrantError("malformed grant")
        grant = self._d.get(_hash(token))
        if grant is None:
            raise GrantError("unknown, expired or revoked grant")
        if grant.expires_at < time.time():
            del self._d[grant.token_hash]
            raise GrantError("grant expired")
        return grant

    async def consume(self, grant):
        current = self._d.get(grant.token_hash)
        if current is None:
            raise GrantError("unknown, expired or revoked grant")
        if current.calls_left <= 0:
            raise GrantError("grant call budget exhausted")
        current.calls_left -= 1
        return current

    async def revoke(self, token):
        self._d.pop(_hash(token), None)

    async def revoke_credential(self, credential_id):
        gone = [h for h, g in self._d.items() if g.credential_id == credential_id]
        for h in gone:
            del self._d[h]
        return len(gone)
