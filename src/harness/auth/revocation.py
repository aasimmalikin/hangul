"""Per-token revocation list, keyed by the JWT `jti` claim.

Service tokens minted by the BFF live for five minutes, so revocation is a
belt-and-braces control for the rare "cut this token off now" case, not the
primary line of defence. That shapes the failure mode: if Redis is
unreachable we *allow* the token and log loudly, rather than lock every user
out of the app because a cache is down (fail-open for an optional check,
fail-closed for the signature/expiry check in api/auth.py).
"""

import time

from harness.cache.redis_client import get_redis
from harness.logging import log

_PREFIX = "revoked:"


async def revoke(jti: str, exp: int) -> None:
    """Mark a token revoked until it would have expired anyway."""
    ttl = max(1, exp - int(time.time()))
    await get_redis().set(f"{_PREFIX}{jti}", "1", ex=ttl)


async def is_revoked(jti: str) -> bool:
    try:
        return await get_redis().get(f"{_PREFIX}{jti}") is not None
    except Exception as e:  # noqa: BLE001
        log.warning("revocation check unavailable; allowing token", error=str(e))
        return False
