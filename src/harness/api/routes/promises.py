"""/promises: Kept your word (harness.promises) -- the user's open promises and
the ones owed to them, the after-meeting answer, chasing, and the switch for
reading email. A foreign id is a 404, like a missing one.

Free keeps and edits promises; the after-meeting answer and chasing are Plus
(402 ``plan_required``), as is reading email (simply not done on Free).
"""

import asyncio
from datetime import UTC, date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from harness.api.auth import get_current_user
from harness.db import promises as db
from harness.promises import service

router = APIRouter()


class PromiseIn(BaseModel):
    direction: Literal["mine", "theirs"]
    what: str = Field(min_length=1, max_length=300)
    who: str = Field("", max_length=120)
    who_email: str = Field("", max_length=255)
    due_on: date | None = None


class PromisePatch(BaseModel):
    status: Literal["open", "done", "dropped"] | None = None
    what: str | None = Field(None, max_length=300)
    who: str | None = Field(None, max_length=120)
    due_on: date | None = None
    clear_due: bool = False


class CaptureIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    meeting_id: str | None = Field(None, max_length=200)


class SettingsIn(BaseModel):
    email_on: bool


def _plan_required(feature: str) -> HTTPException:
    return HTTPException(status_code=402, headers={"X-Reason": "plan_required"},
                         detail={"detail": f"{feature} is part of Plus.", "code": "plan_required", "plan_needed": "plus"})


def _missing() -> HTTPException:
    return HTTPException(status_code=404, detail="No such promise.")


def _asking(uid: str) -> list[dict]:
    state = db.scan_state(uid)
    return [{"id": a["id"], "summary": a.get("summary", ""), "people": a.get("people", []), "at": a.get("at")}
            for a in service.recent_asked(state["asked"], datetime.now(UTC))]


@router.get("/promises")
async def list_promises(status: Literal["open", "done", "dropped", "all"] = "open",
                        user: dict = Depends(get_current_user)) -> dict:
    uid = user["user_id"]

    def read() -> dict:
        return {"promises": [p.as_dict() for p in db.list_for(uid, None if status == "all" else status)],
                "counts": db.counts(uid), "access": service.access(uid),
                "email_on": db.scan_state(uid)["email_on"], "asking": _asking(uid)}
    return await asyncio.to_thread(read)


@router.post("/promises")
async def add_promise(req: PromiseIn, user: dict = Depends(get_current_user)) -> dict:
    try:
        p = await asyncio.to_thread(db.add, user["user_id"], req.direction, req.what, who=req.who,
                                    who_email=req.who_email, due_on=req.due_on, source="chat")
    except db.LimitReached as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return p.as_dict()


@router.patch("/promises/{promise_id}")
async def edit_promise(promise_id: int, req: PromisePatch, user: dict = Depends(get_current_user)) -> dict:
    fields = req.model_dump(exclude_none=True, exclude={"clear_due"})
    if req.clear_due:
        fields["due_on"] = None
    p = await asyncio.to_thread(lambda: db.update(user["user_id"], promise_id, **fields))
    if p is None:
        raise _missing()
    return p.as_dict()


@router.post("/promises/{promise_id}/chase")
async def chase(promise_id: int, user: dict = Depends(get_current_user)) -> dict:
    """What to ask the agent for a follow-up draft. The page sends it as a chat
    message, so the draft and any send go through the normal approval."""
    uid = user["user_id"]
    p = await asyncio.to_thread(db.get, uid, promise_id)
    if p is None:
        raise _missing()
    if p.direction != "theirs":
        raise HTTPException(status_code=422, detail="Only a promise owed to you can be chased.")
    if not (await asyncio.to_thread(service.access, uid))["chase"]:
        raise _plan_required("Chasing promises")
    await asyncio.to_thread(db.mark_chased, uid, promise_id)
    return {"prompt": service.chase_prompt(p)}


@router.post("/promises/capture")
async def capture(req: CaptureIn, user: dict = Depends(get_current_user)) -> dict:
    """The answer to "was anything promised?" after a meeting."""
    uid = user["user_id"]
    if not (await asyncio.to_thread(service.access, uid))["meetings"]:
        raise _plan_required("Keeping track of what was promised in meetings")
    if not await asyncio.to_thread(service._can_spend, uid):
        raise HTTPException(status_code=402, headers={"X-Reason": "insufficient_balance"},
                            detail={"detail": "You've used this month's allowance.", "code": "insufficient_balance"})
    found = await service.capture(uid, req.text, req.meeting_id)
    return {"promises": [p.as_dict() for p in found]}


@router.post("/promises/meetings/{meeting_id}/skip")
async def skip_meeting(meeting_id: str, user: dict = Depends(get_current_user)) -> dict:
    """"Nothing was promised": stop asking about that meeting."""
    await asyncio.to_thread(service.answered, user["user_id"], meeting_id)
    return {"ok": True}


@router.put("/promises/settings")
async def settings(req: SettingsIn, user: dict = Depends(get_current_user)) -> dict:
    await asyncio.to_thread(db.save_scan, user["user_id"], email_on=req.email_on)
    return {"email_on": req.email_on}


@router.get("/promises/people")
async def with_people(emails: str = Query("", max_length=2000), user: dict = Depends(get_current_user)) -> dict:
    """Open promises with these people (comma-separated emails): meeting prep."""
    rows = await asyncio.to_thread(db.with_people, user["user_id"], emails.split(","))
    return {"promises": [p.as_dict() for p in rows]}
