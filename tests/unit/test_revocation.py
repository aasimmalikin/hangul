"""The revocation list must only reject tokens that were actually revoked."""
import asyncio
import pytest

from harness.auth import revocation


class FakeRedis:
    def __init__(self, fail=False):
        self.store, self.fail = {}, fail

    async def get(self, k):
        if self.fail:
            raise ConnectionError("redis down")
        return self.store.get(k)

    async def set(self, k, v, ex=None):
        self.store[k] = v


@pytest.fixture
def redis(monkeypatch):
    r = FakeRedis()
    monkeypatch.setattr(revocation, "get_redis", lambda: r)
    return r


def test_fresh_token_is_not_revoked(redis):
    assert asyncio.run(revocation.is_revoked("abc")) is False


def test_revoked_token_is_revoked(redis):
    asyncio.run(revocation.revoke("abc", exp=2_000_000_000))
    assert asyncio.run(revocation.is_revoked("abc")) is True
    assert asyncio.run(revocation.is_revoked("other")) is False


def test_redis_outage_allows_the_token(monkeypatch):
    monkeypatch.setattr(revocation, "get_redis", lambda: FakeRedis(fail=True))
    assert asyncio.run(revocation.is_revoked("abc")) is False
