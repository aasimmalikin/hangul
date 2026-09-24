"""One run at a time per conversation.

A conversation's transcript is an ordered message list, and an OpenAI message
list is only valid when every ``tool_calls`` entry is followed by its matching
``tool`` reply. Two runs appending to one conversation concurrently -- a
double-submit, two devices, a retried request -- interleave and produce a list
the provider rejects on the *next* turn, long after the damage was done. So a
conversation admits one run at a time.

The claim is a conditional UPDATE rather than a Postgres advisory lock, for two
reasons: an advisory lock is tied to a session that must stay open for the
whole run (which would pin a pooled connection for minutes), and it vanishes if
the replica holding it dies -- but so does any record of *why*. A row with a
timestamp survives the process, so a crashed replica's claim can be identified
and taken over after CLAIM_TTL_S rather than wedging the conversation forever.

This is per conversation and complements ``concurrency.run_slot``, which is per
user: the first keeps one conversation coherent, the second bounds total spend.
A request holds both.
"""

import asyncio
from contextlib import asynccontextmanager

from fastapi import HTTPException
from sqlalchemy import text

from harness.db.base import SessionLocal
from harness.logging import log

# How long a claim stays valid without being released. Longer than the slowest
# plausible run (research mode with a big budget), short enough that a killed
# replica does not lock someone out of their own chat for the rest of the day.
CLAIM_TTL_S = 900


def _claim(conversation_id: str, run_id: str) -> bool:
    """Take the conversation for this run. False = someone else holds it.

    The WHERE does the arbitration, so two concurrent callers cannot both win:
    Postgres serialises the row update and the loser's WHERE no longer matches.
    """
    with SessionLocal() as session:
        row = session.execute(
            text("""
                UPDATE conversations
                   SET active_run_id = :rid, active_run_started_at = now()
                 WHERE id = :cid
                   AND (active_run_id IS NULL
                        OR active_run_started_at < now() - make_interval(secs => :ttl))
             RETURNING id
            """),
            {"cid": conversation_id, "rid": run_id, "ttl": CLAIM_TTL_S},
        ).first()
        session.commit()
        return row is not None


def _release(conversation_id: str, run_id: str) -> None:
    """Drop our claim. Scoped to ``active_run_id = :rid`` so a run whose claim
    was already taken over (it ran past the TTL) cannot clear the new owner's."""
    with SessionLocal() as session:
        session.execute(
            text("""
                UPDATE conversations
                   SET active_run_id = NULL, active_run_started_at = NULL
                 WHERE id = :cid AND active_run_id = :rid
            """),
            {"cid": conversation_id, "rid": run_id},
        )
        session.commit()


def busy() -> HTTPException:
    return HTTPException(
        status_code=409,
        detail="This conversation already has a run in flight. Wait for it to finish.",
        headers={"Retry-After": "5", "X-Reason": "conversation_busy"},
    )


@asynccontextmanager
async def conversation_slot(conversation_id: str, run_id: str):
    """Hold the conversation for the duration of one run, or raise 409.

    SessionLocal is sync SQLAlchemy against a remote Postgres, so both the
    claim and the release go through a worker thread.
    """
    if not await asyncio.to_thread(_claim, conversation_id, run_id):
        log.info("conversation busy", conversation_id=conversation_id, run_id=run_id)
        raise busy()
    try:
        yield
    finally:
        try:
            await asyncio.to_thread(_release, conversation_id, run_id)
        except Exception as e:  # noqa: BLE001
            # The TTL is the backstop: a claim we failed to clear expires.
            log.warning("conversation claim release failed",
                        conversation_id=conversation_id, run_id=run_id, error=str(e))
