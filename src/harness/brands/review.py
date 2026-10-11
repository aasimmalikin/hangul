"""Client review links: an agency sends a post to its client, who opens a
private page (no account), sees every size and the captions, and taps
Approve or Request changes with a comment.

The link is the credential, so it is narrow: it names one post of one user,
expires (``TTL_S``), shows only that post's own files, and the only thing
it can change is that post's review status and comment. Token:
base64url("<post_id>.<user_id>.<expires>") + "." + base64url(HMAC-SHA256),
keyed by a key derived from JWT_SECRET for this purpose only (not the
approve-by-link key, so neither token works as the other).
"""

import base64
import hashlib
import hmac
import time

from harness.config import get_settings

TTL_S = 14 * 24 * 3600


class LinkError(ValueError):
    pass


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _key() -> bytes:
    return hashlib.sha256(b"hangul-review-link:" + get_settings().jwt_secret.encode()).digest()


def make(post_id: int, user_id: str, *, ttl_s: int = TTL_S, now: float | None = None) -> str:
    payload = f"{int(post_id)}.{user_id}.{int((now or time.time()) + ttl_s)}".encode()
    return f"{_b64(payload)}.{_b64(hmac.new(_key(), payload, hashlib.sha256).digest())}"


def read(token: str, *, now: float | None = None) -> tuple[int, str, int]:
    """(post_id, user_id, expires) of a valid, unexpired link; LinkError otherwise."""
    try:
        p64, s64 = token.split(".")
        payload, sig = _unb64(p64), _unb64(s64)
    except (ValueError, TypeError) as e:
        raise LinkError("malformed link") from e
    if not hmac.compare_digest(sig, hmac.new(_key(), payload, hashlib.sha256).digest()):
        raise LinkError("bad signature")
    try:
        post_id, user_id, exp = payload.decode().split(".")
        post, expires = int(post_id), int(exp)
    except ValueError as e:
        raise LinkError("malformed link") from e
    if expires < (now or time.time()):
        raise LinkError("expired")
    return post, user_id, expires


def url(token: str) -> str:
    return get_settings().app_url.rstrip("/") + f"/review/{token}"
