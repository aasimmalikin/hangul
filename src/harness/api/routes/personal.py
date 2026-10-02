"""The user's reminders, lists and notes, for the web UI (the bell, the
checklist cards, /lists). The agent reaches the same data through the
``reminders`` / ``lists`` / ``notes`` tools. A foreign id is a 404, exactly
like a missing one."""

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from harness.api.auth import get_current_user
from harness.db import personal as db

router = APIRouter()


@router.get("/reminders")
async def reminders(scope: str = "upcoming", user: dict = Depends(get_current_user)) -> list[dict]:
    """upcoming = not yet due; due = fired and not dismissed (the bell)."""
    statuses = {"upcoming": ("pending",), "due": ("sent",), "open": ("pending", "sent")}.get(scope)
    if statuses is None:
        raise HTTPException(status_code=422, detail="scope must be upcoming, due or open.")
    rows = await asyncio.to_thread(db.list_reminders, user["user_id"], statuses)
    return [r.as_dict() for r in rows]


@router.post("/reminders/{reminder_id}/done")
async def reminder_done(reminder_id: int, user: dict = Depends(get_current_user)) -> dict:
    r = await asyncio.to_thread(db.set_reminder_status, user["user_id"], reminder_id, "done")
    if r is None:
        raise HTTPException(status_code=404, detail="No such reminder.")
    return r.as_dict()


@router.delete("/reminders/{reminder_id}")
async def reminder_cancel(reminder_id: int, user: dict = Depends(get_current_user)) -> dict:
    r = await asyncio.to_thread(db.set_reminder_status, user["user_id"], reminder_id, "cancelled")
    if r is None:
        raise HTTPException(status_code=404, detail="No such reminder.")
    return r.as_dict()


@router.get("/lists")
async def lists(include_done: bool = False, user: dict = Depends(get_current_user)) -> dict:
    rows = await asyncio.to_thread(db.list_todos, user["user_id"], None, include_done)
    grouped: dict[str, list[dict]] = {}
    for r in rows:
        grouped.setdefault(r.list_name, []).append(r.as_dict())
    return {"lists": grouped}


class ItemAdd(BaseModel):
    list: str = "To-do"
    text: str = Field(min_length=1, max_length=500)


@router.post("/lists")
async def item_add(body: ItemAdd, user: dict = Depends(get_current_user)) -> dict:
    try:
        rows = await asyncio.to_thread(db.add_todos, user["user_id"], body.list, [body.text])
    except db.LimitReached as e:
        raise HTTPException(status_code=409, detail=str(e))
    return rows[0].as_dict()


class ItemPatch(BaseModel):
    done: bool


@router.patch("/lists/items/{item_id}")
async def item_patch(item_id: int, body: ItemPatch, user: dict = Depends(get_current_user)) -> dict:
    r = await asyncio.to_thread(db.set_todo_done, user["user_id"], item_id, body.done)
    if r is None:
        raise HTTPException(status_code=404, detail="No such item.")
    return r.as_dict()


@router.delete("/lists/items/{item_id}")
async def item_delete(item_id: int, user: dict = Depends(get_current_user)) -> dict:
    if not await asyncio.to_thread(db.delete_todo, user["user_id"], item_id):
        raise HTTPException(status_code=404, detail="No such item.")
    return {"deleted": item_id}


@router.get("/notes")
async def notes(q: str = "", user: dict = Depends(get_current_user)) -> list[dict]:
    rows = await asyncio.to_thread(db.search_notes, user["user_id"], q[:200], 100)
    return [n.as_dict() for n in rows]


@router.delete("/notes/{note_id}")
async def note_delete(note_id: int, user: dict = Depends(get_current_user)) -> dict:
    if not await asyncio.to_thread(db.delete_note, user["user_id"], note_id):
        raise HTTPException(status_code=404, detail="No such note.")
    return {"deleted": note_id}
