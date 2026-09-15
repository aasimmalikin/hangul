"""Per-user cap on simultaneous agent runs.

Every run costs model tokens and holds a worker slot for the whole stream, so
one user opening many tabs (or a client retrying in a loop) must not be able
to starve everyone else or run up a bill. The cap is per process: with
several replicas the effective limit is cap × replicas, which is still a
bound. A shared Redis counter would make it exact; not needed yet.
"""

import asyncio
from collections import defaultdict
from contextlib import asynccontextmanager

from fastapi import HTTPException

MAX_IN_FLIGHT_PER_USER = 3

_in_flight: dict[str, int] = defaultdict(int)
_lock = asyncio.Lock()


@asynccontextmanager
async def run_slot(user_id: str):
    async with _lock:
        if _in_flight[user_id] >= MAX_IN_FLIGHT_PER_USER:
            raise HTTPException(
                status_code=429,
                detail="Too many requests in flight. Wait for your current answer to finish.",
                headers={"Retry-After": "5"},
            )
        _in_flight[user_id] += 1
    try:
        yield
    finally:
        async with _lock:
            _in_flight[user_id] -= 1
            if _in_flight[user_id] <= 0:
                del _in_flight[user_id]


def in_flight(user_id: str) -> int:
    return _in_flight.get(user_id, 0)
