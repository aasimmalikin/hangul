"""Approve-by-link: a signed, single-action link in the "needs your approval" email
and push notification, so a scheduled task can be approved without opening the
app or signing in.

Why that is acceptable: Hangul signs people in with links mailed to the same
address, so whoever can read the inbox can already get in; the link opens no new
door. It is still narrow: it names one run of one user, expires with the action
(scheduler.APPROVAL_TTL_S), and works once, because approving claims the pending
action (CheckpointStore.claim_pending) exactly as the app does. Opening the link
(a GET -- mail scanners prefetch those) only shows the action; deciding is a POST
from a button on the page.

Token: base64url("<run_id>.<user_id>.<expires unix>") + "." + base64url(HMAC-SHA256),
keyed by a key derived from JWT_SECRET for this purpose only.
"""

import base64
import hashlib
import hmac
import time

from harness.config import get_settings

TTL_S = 24 * 3600


class LinkError(ValueError):
    pass


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _key() -> bytes:
    return hashlib.sha256(b"hangul-approval-link:" + get_settings().jwt_secret.encode()).digest()


def make(run_id: str, user_id: str, *, ttl_s: int = TTL_S, now: float | None = None) -> str:
    payload = f"{run_id}.{user_id}.{int((now or time.time()) + ttl_s)}".encode()
    return f"{_b64(payload)}.{_b64(hmac.new(_key(), payload, hashlib.sha256).digest())}"


def read(token: str, *, now: float | None = None) -> tuple[str, str]:
    """(run_id, user_id) of a valid, unexpired link; LinkError otherwise."""
    try:
        p64, s64 = token.split(".")
        payload, sig = _unb64(p64), _unb64(s64)
    except (ValueError, TypeError) as e:
        raise LinkError("malformed link") from e
    if not hmac.compare_digest(sig, hmac.new(_key(), payload, hashlib.sha256).digest()):
        raise LinkError("bad signature")
    try:
        run_id, user_id, exp = payload.decode().split(".")
        expires = int(exp)
    except ValueError as e:
        raise LinkError("malformed link") from e
    if expires < (now or time.time()):
        raise LinkError("expired")
    return run_id, user_id


def url(token: str) -> str:
    return get_settings().app_url.rstrip("/") + f"/approve/{token}"
