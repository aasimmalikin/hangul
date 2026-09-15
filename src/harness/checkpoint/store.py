import json
from pathlib import Path
import sqlalchemy as sa
from harness.checkpoint.checkpoint import Checkpoint
from pydantic import BaseModel, Field
from sqlalchemy.dialects.postgresql import insert
from harness.db.base import SessionLocal
from harness.db.models import Thread


class CheckpointStore:

    def load(self, thread_id: str)->Checkpoint | None:
        with SessionLocal() as session:
            row = session.get(Thread, thread_id)
            if row is None:
                return None
            return Checkpoint(
                thread_id=row.thread_id,
                message=row.message or [],
                step=row.step,
                status = row.status,
                completed_calls=row.completed_calls or {},
                pending_tool=row.pending_tool,
                user_id=row.user_id,
            )

    def claim_pending(self, thread_id: str, user_id: str) -> Checkpoint | None:
        """Atomically take the pending action off a thread the caller owns.

        Two concurrent /approve calls (a double-click, a retried request) must
        not both execute a destructive tool. A single conditional UPDATE lets
        exactly one caller win; the loser sees None, same as "nothing pending".
        Ownership is part of the WHERE so a foreign thread is indistinguishable
        from a missing one.
        """
        with SessionLocal() as session:
            row = (
                session.query(Thread)
                .filter(Thread.thread_id == thread_id,
                        Thread.user_id == user_id,
                        Thread.pending_tool.isnot(None))
                .with_for_update(skip_locked=True)
                .one_or_none()
            )
            if row is None:
                return None
            cp = Checkpoint(
                thread_id=row.thread_id,
                message=row.message or [],
                step=row.step,
                status=row.status,
                completed_calls=row.completed_calls or {},
                pending_tool=row.pending_tool,
                user_id=row.user_id,
            )
            row.pending_tool = None
            row.status = "running"
            session.commit()
            return cp
    
    def save(self, cp: Checkpoint)-> None:
        values = {
            "thread_id": cp.thread_id, 
            "message": cp.message,
            "step": cp.step,
            "status": cp.status,
            "completed_calls":cp.completed_calls,
            "pending_tool": cp.pending_tool,
            "user_id": cp.user_id,
        }
        stmt = insert(Thread).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements = [Thread.thread_id], 
            set_ = {
                "message": stmt.excluded.message,
                "step": stmt.excluded.step,
                "status": stmt.excluded.status,
                "completed_calls": stmt.excluded.completed_calls,
                "pending_tool":stmt.excluded.pending_tool,
                # Never let a later save blank the owner.
                "user_id": sa.func.coalesce(stmt.excluded.user_id, Thread.user_id),
            },
        )
        with SessionLocal() as session:
            session.execute(stmt)
            session.commit()
    
    def delete(self, thread_id: str)->None:
        with SessionLocal() as session:
            row = session.get(Thread, thread_id)
            if row is not None:
                session.delete(row)
                session.commit()


