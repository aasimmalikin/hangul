"""Replies you owe: Gmail threads where someone wrote to the user directly and
is still waiting for an answer.

A thread counts when its newest message (still in the inbox, Primary tab) is
from someone else, was sent *to* the user (not just Cc'd, not a mailing list),
isn't automated (newsletters, receipts, notifications, no-reply senders), and
has been waiting at least OWED_AFTER_H hours but no more than MAX_DAYS days.
Used by the Today card and the gmail__replies_owed tool. The rules live in
``owed()``, a pure function, so they can be tested without Gmail.
"""

import asyncio
import re
import time
from datetime import datetime, timedelta
from email.utils import getaddresses, parseaddr

import httpx

from harness.connectors.google_rest import GMAIL, _header, _request

OWED_AFTER_H = 24          # a reply isn't "owed" the minute a mail arrives
MAX_DAYS = 14              # older than this is history, not a to-do
MAX_THREADS = 25           # newest inbox threads looked at
MAX_RECIPIENTS = 10        # a mail to a crowd isn't waiting on this user
CACHE_S = 10 * 60
HEADERS = ["From", "To", "Cc", "Subject", "Date", "List-Unsubscribe", "List-Id", "Precedence", "Auto-Submitted"]

_AUTOMATED_SENDER = re.compile(
    r"(^|[._+-])(no-?reply|do-?not-?reply|notifications?|notify|alerts?|mailer-daemon|postmaster|bounces?|"
    r"newsletters?|updates|support|billing|receipts?)([._+-]|@)", re.I)
_SKIP_LABELS = {"CATEGORY_PROMOTIONS", "CATEGORY_SOCIAL", "CATEGORY_UPDATES", "CATEGORY_FORUMS", "SPAM", "TRASH"}

_cache: dict[str, tuple[float, list[dict]]] = {}
_me: dict[str, str] = {}


def _automated(msg: dict) -> bool:
    if _header(msg, "List-Unsubscribe") or _header(msg, "List-Id"):
        return True
    if _header(msg, "Precedence").lower() in ("bulk", "list", "junk"):
        return True
    auto = _header(msg, "Auto-Submitted").lower()
    if auto and auto != "no":
        return True
    return bool(_AUTOMATED_SENDER.search(parseaddr(_header(msg, "From"))[1]))


def owed(threads: list[dict], me: str, now: datetime) -> list[dict]:
    """The threads (Gmail ``threads.get`` metadata) waiting on ``me``, longest wait first."""
    me = me.lower()
    out = []
    for t in threads:
        msgs = t.get("messages") or []
        if not msgs:
            continue
        last = msgs[-1]
        labels = set(last.get("labelIds", []))
        name, sender = parseaddr(_header(last, "From"))
        if sender.lower() == me or "SENT" in labels or "INBOX" not in labels or labels & _SKIP_LABELS:
            continue                                   # answered, archived, or not a personal mail
        to = [a.lower() for _, a in getaddresses([_header(last, "To")]) if a]
        cc = [a for _, a in getaddresses([_header(last, "Cc")]) if a]
        if me not in to or len(to) + len(cc) > MAX_RECIPIENTS or _automated(last):
            continue
        received = datetime.fromtimestamp(int(last.get("internalDate", "0")) / 1000, tz=now.tzinfo)
        waited = now - received
        if not (timedelta(hours=OWED_AFTER_H) <= waited <= timedelta(days=MAX_DAYS)):
            continue
        out.append({"thread_id": t.get("id"), "from": name or sender, "email": sender,
                    "subject": _header(last, "Subject") or "(no subject)", "snippet": last.get("snippet", ""),
                    "received": received.isoformat(), "waiting_days": waited.days,
                    "unread": "UNREAD" in labels})
    return sorted(out, key=lambda r: r["received"])


async def _my_address(user_id: str, http: httpx.AsyncClient | None) -> str:
    if user_id not in _me:
        r = await _request(http, user_id, "gmail", "GET", f"{GMAIL}/profile")
        _me[user_id] = r.json().get("emailAddress", "")
    return _me[user_id]


async def replies_owed(user_id: str, now: datetime, http: httpx.AsyncClient | None = None,
                       *, fresh: bool = False) -> list[dict]:
    """Replies the user owes, cached for CACHE_S (raises GoogleNotConnected / GoogleApiError)."""
    hit = _cache.get(user_id)
    if hit and not fresh and time.monotonic() - hit[0] < CACHE_S:
        return hit[1]
    me = await _my_address(user_id, http)
    q = f"in:inbox category:primary newer_than:{MAX_DAYS}d -from:me"
    r = await _request(http, user_id, "gmail", "GET", f"{GMAIL}/threads", params={"q": q, "maxResults": MAX_THREADS})
    ids = [t["id"] for t in r.json().get("threads", [])]
    gate = asyncio.Semaphore(6)

    async def get(tid: str) -> dict:
        async with gate:
            res = await _request(http, user_id, "gmail", "GET", f"{GMAIL}/threads/{tid}",
                                 params={"format": "metadata", "metadataHeaders": HEADERS})
            return res.json()
    threads = await asyncio.gather(*(get(t) for t in ids))
    found = owed(list(threads), me, now)
    _cache[user_id] = (time.monotonic(), found)
    return found
