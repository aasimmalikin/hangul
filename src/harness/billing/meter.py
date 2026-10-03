"""The run meter: the costs a question causes besides its own model tokens.

Embeddings (document search, uploads), web searches, conversation summaries
and the optional security classifier all cost real money. Without this they
were free to the user and paid by the operator -- heavy researchers cost
more than their plan covered.

``metering(user_id)`` opens a meter for the current task (a ContextVar, so it
follows the run into ``asyncio.to_thread`` and nested calls without changing
any function signature); ``add(usd, kind)`` records a cost; the run adds
``meter.extra`` to its model cost, so a question is still ONE ledger entry.
Outside a run (an upload) the meter settles its own total when it closes.
Code with no meter open (CLI ingest, tests) just isn't charged.
"""

import asyncio
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from decimal import Decimal

from harness.config import get_settings
from harness.logging import log


@dataclass
class Meter:
    user_id: str
    thread_id: str | None = None
    extra: Decimal = Decimal("0")
    by_kind: dict[str, Decimal] = field(default_factory=dict)

    def add(self, usd: float, kind: str) -> None:
        if usd <= 0:
            return
        d = Decimal(str(round(usd, 8)))
        self.extra += d
        self.by_kind[kind] = self.by_kind.get(kind, Decimal("0")) + d


_current: ContextVar[Meter | None] = ContextVar("hangul_meter", default=None)


def current() -> Meter | None:
    return _current.get()


def add(usd: float, kind: str) -> None:
    """Record a cost on the open meter (no-op when none is open)."""
    m = _current.get()
    if m is not None:
        m.add(usd, kind)


def embedding_cost(tokens: int) -> float:
    return tokens / 1_000_000 * get_settings().embedding_usd_per_m


@asynccontextmanager
async def metering(user_id: str, thread_id: str | None = None, *, settle_on_exit: bool = False):
    """Open a meter for this task. ``settle_on_exit`` charges the total when
    the block ends (uploads); a run instead folds ``extra`` into its run cost."""
    m = Meter(user_id=user_id, thread_id=thread_id)
    token = _current.set(m)
    try:
        yield m
    finally:
        _current.reset(token)
        if settle_on_exit and m.extra > 0:
            try:
                from harness.billing import entitlements
                await asyncio.to_thread(entitlements.settle, user_id, m.extra, thread_id)
            except Exception as e:  # noqa: BLE001 - bookkeeping must not fail the request
                log.warning("metered cost not recorded", error=str(e))
