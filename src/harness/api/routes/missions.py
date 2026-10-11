"""/missions: the jobs Hangul is carrying through (harness.missions), the
owner's go-ahead, the trust they've given it, and what it earned.

A foreign id is a 404, like a missing one. Missions are Plus and up; deciding on one
after a downgrade is a 402, but undoing one and turning autonomy off always work.
"""

import asyncio
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from harness.api.auth import get_current_user
from harness.db import missions as db
from harness.db import sales as sales_db
from harness.missions import allowed, report, slow_day

router = APIRouter()


class DecisionIn(BaseModel):
    decision: str                     # approve | reject


class TrustIn(BaseModel):
    auto: bool


def _plan_required() -> HTTPException:
    return HTTPException(status_code=402, headers={"X-Reason": "plan_required"},
                         detail={"detail": "Hangul handling your slow days is part of Plus.", "code": "plan_required",
                                 "plan_needed": "plus"})


def _trusts(user_id: str) -> list[dict]:
    names = {b["id"]: b["name"] for b in sales_db.list_for(user_id)}
    out = []
    for t in db.trusts(user_id):
        kind, _, bid = t["scope"].partition(":")
        if kind == slow_day.KIND and bid.isdigit() and int(bid) in names:
            out.append({**t, "business_id": int(bid), "business_name": names[int(bid)],
                        "trust_after": slow_day.TRUST_AFTER})
    return out


@router.get("/missions")
async def list_missions(business_id: int | None = None, user: dict = Depends(get_current_user)) -> dict:
    uid = user["user_id"]
    today = await asyncio.to_thread(slow_day._local, uid)
    rows = await asyncio.to_thread(lambda: db.list_for(uid, limit=40, business_id=business_id))
    return {"allowed": await asyncio.to_thread(allowed, uid),
            "missions": [m for m in rows if m["kind"] == slow_day.KIND],
            "trust": await asyncio.to_thread(_trusts, uid),
            "this_month": await asyncio.to_thread(report.summary, uid, today[0]),
            "last_month": await asyncio.to_thread(report.summary, uid, report.prev_month(today[0]))}


@router.get("/missions/report")
async def month_report(month: str = Query(pattern=r"^\d{4}-\d{2}$"), user: dict = Depends(get_current_user)) -> dict:
    try:
        first = date.fromisoformat(month + "-01")
    except ValueError as e:
        raise HTTPException(status_code=422, detail="month must be YYYY-MM") from e
    s = await asyncio.to_thread(report.summary, user["user_id"], first)
    return {**s, "text": report.text(s)}


async def _mine(user_id: str, mission_id: int) -> dict:
    m = await asyncio.to_thread(db.get, user_id, mission_id)
    if m is None:
        raise HTTPException(status_code=404, detail="No such mission.")
    return m


@router.get("/missions/{mission_id}")
async def get_mission(mission_id: int, user: dict = Depends(get_current_user)) -> dict:
    m = await _mine(user["user_id"], mission_id)
    out = {**m, "can_undo": False}
    if m["kind"] == slow_day.KIND:
        today, _ = await asyncio.to_thread(slow_day._local, user["user_id"])
        out["can_undo"] = (bool(m["data"].get("approved")) and m["status"] in db.OPEN
                           and today <= date.fromisoformat(m["target_day"]))
        out["trust"] = await asyncio.to_thread(db.trust, user["user_id"], slow_day.scope(m["business_id"]))
        out["trust_after"] = slow_day.TRUST_AFTER
    return out


@router.post("/missions/{mission_id}/decide")
async def decide(mission_id: int, body: DecisionIn, user: dict = Depends(get_current_user)) -> dict:
    uid = user["user_id"]
    if body.decision not in ("approve", "reject"):
        raise HTTPException(status_code=422, detail="decision must be approve or reject")
    await _mine(uid, mission_id)
    if body.decision == "approve" and not await asyncio.to_thread(allowed, uid):
        raise _plan_required()
    try:
        m, reply = await slow_day.decide(uid, mission_id, body.decision == "approve")
    except LookupError as e:
        raise HTTPException(status_code=404, detail="No such mission.") from e
    except slow_day.AlreadyDecided as e:
        raise HTTPException(status_code=409, headers={"X-Reason": "mission_decided"},
                            detail="That one has expired." if str(e) == "expired" else "That was already decided.") from e
    return {**m, "message": reply}


@router.post("/missions/{mission_id}/undo")
async def undo(mission_id: int, user: dict = Depends(get_current_user)) -> dict:
    await _mine(user["user_id"], mission_id)
    try:
        return await slow_day.undo(user["user_id"], mission_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail="No such mission.") from e
    except slow_day.AlreadyDecided as e:
        raise HTTPException(status_code=409, headers={"X-Reason": "mission_decided"},
                            detail="It's too late to undo this one.") from e


@router.put("/missions/trust/{business_id}")
async def set_trust(business_id: int, body: TrustIn, user: dict = Depends(get_current_user)) -> dict:
    uid = user["user_id"]
    if await asyncio.to_thread(sales_db.get, uid, business_id) is None:
        raise HTTPException(status_code=404, detail="No such business.")
    if body.auto and not await asyncio.to_thread(allowed, uid):
        raise _plan_required()
    return await slow_day.set_auto(uid, business_id, body.auto)
