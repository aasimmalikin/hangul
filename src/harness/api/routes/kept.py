"""GET /kept: the Kept tab -- everything the user asked Hangul to do that
lasts beyond the reply, in their own words (db/kept.py). ``q`` searches all
time; without it the timeline is the last week plus everything to come.
GET /kept/count is the tab's badge: approvals waiting on the user."""

import asyncio

from fastapi import APIRouter, Depends, Query

from harness.api.auth import get_current_user
from harness.db import kept as db

router = APIRouter()


def _file_count(user_id: str) -> int:
    from harness.tools.builtin.files import user_folder
    try:
        return sum(1 for p in user_folder(user_id).iterdir() if p.is_file() and not p.name.startswith("."))
    except OSError:
        return 0


@router.get("/kept")
async def kept(q: str = Query("", max_length=200), user: dict = Depends(get_current_user)) -> dict:
    out, files = await asyncio.gather(asyncio.to_thread(db.kept, user["user_id"], q),
                                      asyncio.to_thread(_file_count, user["user_id"]))
    out["holding"]["files"] = files
    return out


@router.get("/kept/count")
async def kept_count(user: dict = Depends(get_current_user)) -> dict:
    return {"needs_you": await asyncio.to_thread(db.needs_you_count, user["user_id"])}
