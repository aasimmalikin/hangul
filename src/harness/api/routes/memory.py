"""GET/DELETE endpoints for a user's own memories.

The responsible half of a memory system: since we store derived facts about
users, they must be able to see and delete them.
Everything here is scoped to the authenticated user.
"""
import asyncio
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from harness.api.auth import get_current_user
from harness.db.memory import deactivate_memory, list_active

router = APIRouter()


class MemoryItem(BaseModel):
    id: int
    kind: str
    content: str
    created_at: datetime


@router.get("/memory", response_model=list[MemoryItem])
async def get_memory(user: dict = Depends(get_current_user)) -> list[MemoryItem]:
    """All active memory items for the current user, newest first."""
    # db.memory is synchronous SQLAlchemy; run it off the event loop like
    # recall.py and ask.py do, so a slow DB does not stall other requests.
    rows = await asyncio.to_thread(list_active, user["user_id"])
    return [MemoryItem(id=r.id, kind=r.kind, content=r.content, created_at=r.created_at) for r in rows]


@router.delete("/memory/{memory_id}")
async def delete_memory(memory_id: int, user: dict = Depends(get_current_user)) -> dict:
    """Deactivate one memory item. 404 if it does not exist, is already
    inactive, or belongs to someone else -- the three are indistinguishable
    on purpose so ids cannot be probed across users."""
    ok = await asyncio.to_thread(deactivate_memory, user["user_id"], memory_id)
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "memory not found")
    return {"deleted": memory_id}
