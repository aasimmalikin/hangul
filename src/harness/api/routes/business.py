"""/business: How's business (harness.sales).

Logging and history are on every plan; what the overview includes follows
``sales.service.access``. A business past the plan's count is ``paused``
(402 ``business_limit`` when used); a foreign id is a 404, like a missing one.
"""

import asyncio
from datetime import date, timedelta

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from harness.api.auth import get_current_user
from harness.db import sales as db
from harness.launch import kinds as launch_kinds
from harness.sales import imports, service, shop_state

router = APIRouter()
KINDS = tuple(launch_kinds.KINDS) + ("other",)


class BusinessIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    kind: str = Field(default="retail_shop", max_length=32)
    city: str = Field(default="", max_length=80)
    brand_id: int | None = None
    launch_plan_id: int | None = None
    nudges: bool = True


class BusinessPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    kind: str | None = Field(default=None, max_length=32)
    city: str | None = Field(default=None, max_length=80)
    brand_id: int | None = None
    launch_plan_id: int | None = None
    nudges: bool | None = None
    unlink: list[str] = Field(default_factory=list)       # "brand" | "plan"


class DayIn(BaseModel):
    day: date | None = None                                # default: today, in the user's timezone
    sales: float = Field(default=0, ge=0, le=1e9)
    bills: int | None = Field(default=None, ge=0, le=1_000_000)
    closed: bool = False
    partial: bool = False
    promo: bool | None = None
    add: bool = False
    note: str = Field(default="", max_length=200)


async def _usable(user_id: str, business_id: int) -> dict:
    b = await asyncio.to_thread(db.get, user_id, business_id)
    if b is None:
        raise HTTPException(status_code=404, detail="No such business.")
    if b["paused"]:
        raise HTTPException(status_code=402, headers={"X-Reason": "business_limit"},
                            detail={"detail": "This business is paused on your plan. Pro tracks up to 5 businesses.",
                                    "code": "business_limit", "plan_needed": "pro"})
    return b


def _check_links(user_id: str, brand_id: int | None, plan_id: int | None) -> None:
    if brand_id:
        from harness.db import brands as brands_db
        if brands_db.get(user_id, brand_id) is None:
            raise HTTPException(status_code=422, detail="No such brand.")
    if plan_id:
        from harness.db import launch as launch_db
        if launch_db.get(user_id, plan_id) is None:
            raise HTTPException(status_code=422, detail="No such launch plan.")


@router.get("/business")
async def list_businesses(user: dict = Depends(get_current_user)) -> dict:
    uid = user["user_id"]
    rows = await asyncio.to_thread(db.list_for, uid)
    slots = await asyncio.to_thread(db.slots, uid)
    return {"businesses": rows, "slots": slots, "can_add": len(rows) < slots,
            "access": await asyncio.to_thread(service.access, uid),
            "kinds": [{"key": k["key"], "label": k["label"]} for k in launch_kinds.catalogue()] + [{"key": "other", "label": "Something else"}]}


@router.post("/business")
async def create_business(body: BusinessIn, user: dict = Depends(get_current_user)) -> dict:
    shop_state.forget(user["user_id"])               # the chat's shop block is rebuilt next turn
    uid = user["user_id"]
    if body.kind not in KINDS:
        raise HTTPException(status_code=422, detail=f"kind must be one of {', '.join(KINDS)}")
    await asyncio.to_thread(_check_links, uid, body.brand_id, body.launch_plan_id)
    try:
        return await asyncio.to_thread(lambda: db.create(uid, **body.model_dump()))
    except db.LimitReached as e:
        raise HTTPException(status_code=402, headers={"X-Reason": "business_limit"},
                            detail={"detail": f"Your plan includes {e.slots} business. Pro tracks up to 5.",
                                    "code": "business_limit", "plan_needed": "pro"}) from e


@router.patch("/business/{business_id}")
async def edit_business(business_id: int, body: BusinessPatch, user: dict = Depends(get_current_user)) -> dict:
    shop_state.forget(user["user_id"])               # the chat's shop block is rebuilt next turn
    uid = user["user_id"]
    await _usable(uid, business_id)
    if body.kind is not None and body.kind not in KINDS:
        raise HTTPException(status_code=422, detail=f"kind must be one of {', '.join(KINDS)}")
    await asyncio.to_thread(_check_links, uid, body.brand_id, body.launch_plan_id)
    fields = body.model_dump(exclude_none=True, exclude={"unlink"})
    if "brand" in body.unlink:
        fields["brand_id"] = None
    if "plan" in body.unlink:
        fields["launch_plan_id"] = None
    if "city" in fields:
        fields.update(lat=None, lon=None)                   # look the new city up again
    return await asyncio.to_thread(lambda: db.update(uid, business_id, **fields))


@router.delete("/business/{business_id}")
async def delete_business(business_id: int, user: dict = Depends(get_current_user)) -> dict:
    shop_state.forget(user["user_id"])               # the chat's shop block is rebuilt next turn
    if not await asyncio.to_thread(db.hide, user["user_id"], business_id):
        raise HTTPException(status_code=404, detail="No such business.")
    return {"ok": True}


@router.get("/business/{business_id}/overview")
async def overview(business_id: int, user: dict = Depends(get_current_user)) -> dict:
    uid = user["user_id"]
    await _usable(uid, business_id)
    return await service.overview(uid, business_id)


@router.post("/business/{business_id}/days")
async def log_day(business_id: int, body: DayIn, user: dict = Depends(get_current_user)) -> dict:
    shop_state.forget(user["user_id"])               # the chat's shop block is rebuilt next turn
    uid = user["user_id"]
    await _usable(uid, business_id)
    today = await asyncio.to_thread(service.local_today, uid)
    day = body.day or today
    if day > today + timedelta(days=1):
        raise HTTPException(status_code=422, detail="That day hasn't happened yet.")
    if day < today - timedelta(days=service.HISTORY_DAYS):
        raise HTTPException(status_code=422, detail="That's too far back; import a spreadsheet instead.")
    if day > today and not body.closed:
        raise HTTPException(status_code=422, detail="Only a closure can be logged ahead (\"closed tomorrow\").")
    return await asyncio.to_thread(lambda: db.log_day(business_id, day, sales=0 if body.closed else body.sales,
                                                      bills=None if body.closed else body.bills, closed=body.closed,
                                                      partial=body.partial, promo=body.promo, source="page",
                                                      note=body.note, add=body.add))


@router.delete("/business/{business_id}/days/{day}")
async def delete_day(business_id: int, day: date, user: dict = Depends(get_current_user)) -> dict:
    shop_state.forget(user["user_id"])               # the chat's shop block is rebuilt next turn
    await _usable(user["user_id"], business_id)
    if not await asyncio.to_thread(db.delete_day, business_id, day):
        raise HTTPException(status_code=404, detail="Nothing logged that day.")
    return {"ok": True}


@router.post("/business/{business_id}/import")
async def import_sales(business_id: int, file: UploadFile = File(...), date_col: str = Form(""),
                       amount_col: str = Form(""), replace: bool = Form(False), preview: bool = Form(False),
                       user: dict = Depends(get_current_user)) -> dict:
    """A sales report from a billing app, Tally, Petpooja or a UPI statement.
    ``preview`` reads it without saving, so the page can show what it found."""
    shop_state.forget(user["user_id"])               # the chat's shop block is rebuilt next turn
    uid = user["user_id"]
    await _usable(uid, business_id)
    data = await file.read(imports.MAX_BYTES + 1)
    try:
        got = await asyncio.to_thread(imports.parse, data, file.filename or "sales.xlsx",
                                      date_col=date_col or None, amount_col=amount_col or None)
    except imports.ImportProblem as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    today = await asyncio.to_thread(service.local_today, uid)
    days = [d for d in got.days if date.fromisoformat(d["day"]) <= today]
    result = {**got.as_dict(), "days": days[-400:], "future_skipped": len(got.days) - len(days)}
    if preview:
        return {**result, "saved": None}
    saved = await asyncio.to_thread(db.import_days, business_id, days[-400:], replace=replace)
    return {**result, "saved": saved}


@router.post("/business/{business_id}/ideas/{key}/use")
async def use_idea(business_id: int, key: str, user: dict = Depends(get_current_user)) -> dict:
    shop_state.forget(user["user_id"])               # the chat's shop block is rebuilt next turn
    uid = user["user_id"]
    await _usable(uid, business_id)
    try:
        return await service.use_idea(uid, business_id, key)
    except PermissionError as e:
        raise HTTPException(status_code=402, headers={"X-Reason": "plan_required"},
                            detail={"detail": str(e), "code": "plan_required", "plan_needed": "pro"}) from e
