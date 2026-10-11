"""/launch: plans for starting a business (harness.launch).

Every plan gets the checklist and the calculator with Hangul's estimates;
searching live prices and sellers (``live``) is Plus and up, a few a month,
and runs in the background (the page polls ``GET /launch/{id}`` while
``status == "sourcing"``). When sourcing isn't allowed the plan is still
made, and ``access`` says why, so the page can show the upgrade. A foreign
id is a 404, exactly like a missing one.
"""

import asyncio
import re

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from harness.api.auth import get_current_user
from harness.config import get_settings
from harness.db import launch as db
from harness.launch import export, kinds, pipeline
from harness.launch import plan as planner

router = APIRouter()


class LaunchIn(BaseModel):
    kind: str = Field(max_length=32)
    city: str = Field(min_length=1, max_length=80)
    area: str = Field(default="", max_length=120)
    size: str = Field(max_length=8)
    renting: str = Field(default="yes", max_length=8)
    budget: float | None = Field(default=None, ge=0, le=planner.MAX_BUDGET)
    start: str = Field(default="", max_length=60)
    note: str = Field(default="", max_length=500)
    live: bool = True                  # search live prices (when the plan allows)


class ItemEdit(BaseModel):
    amount: float | None = None
    qty: int | None = None
    include: bool | None = None


class LaunchPatch(BaseModel):
    price: float | None = None
    units_per_day: float | None = None
    days_per_month: float | None = None
    working_capital_months: float | None = None
    variable: dict[str, float] | None = None
    items: dict[str, ItemEdit] | None = Field(default=None, max_length=200)
    title: str | None = Field(default=None, min_length=1, max_length=120)


async def _own(user_id: str, plan_id: int) -> dict:
    p = await asyncio.to_thread(db.get, user_id, plan_id)
    if p is None:
        raise HTTPException(status_code=404, detail="No such plan.")
    return p


@router.get("/launch/kinds")
async def launch_kinds(user: dict = Depends(get_current_user)) -> dict:
    acc = await asyncio.to_thread(pipeline.access, user["user_id"])
    return {"kinds": kinds.catalogue(), "renting": list(kinds.RENTING), "access": acc.as_dict(),
            "version": kinds.TEMPLATES_VERSION}


@router.get("/launch")
async def list_plans(user: dict = Depends(get_current_user)) -> list[dict]:
    return await asyncio.to_thread(db.list_for, user["user_id"])


@router.post("/launch")
async def create_plan(body: LaunchIn, user: dict = Depends(get_current_user)) -> dict:
    answers = body.model_dump(exclude={"live"})
    try:
        p, acc = await pipeline.create(user["user_id"], answers, live=body.live)
    except planner.BadAnswer as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return {"plan": p, "access": acc.as_dict()}


@router.get("/launch/{plan_id}")
async def get_plan(plan_id: int, user: dict = Depends(get_current_user)) -> dict:
    return await _own(user["user_id"], plan_id)


@router.patch("/launch/{plan_id}")
async def edit_plan(plan_id: int, body: LaunchPatch, user: dict = Depends(get_current_user)) -> dict:
    uid = user["user_id"]
    p = await _own(uid, plan_id)
    patch = body.model_dump(exclude_none=True)
    if "items" in patch:
        patch["items"] = {k: {kk: vv for kk, vv in v.items() if vv is not None} for k, v in patch["items"].items()}
    try:
        items, assumptions = planner.apply_edits(p["items"], p["assumptions"], patch)
    except planner.BadAnswer as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    fields = {"items": items, "assumptions": assumptions}
    if body.title:
        fields["title"] = body.title.strip()
    out = await asyncio.to_thread(db.update, uid, plan_id, **fields)
    if out is None:
        raise HTTPException(status_code=404, detail="No such plan.")
    return out


@router.post("/launch/{plan_id}/source")
async def source_plan(plan_id: int, user: dict = Depends(get_current_user)) -> dict:
    """Search live prices for a plan made with estimates (after an upgrade, or
    to try again after a failure)."""
    uid = user["user_id"]
    p = await _own(uid, plan_id)
    if p["status"] == "sourcing":
        raise HTTPException(status_code=409, headers={"X-Reason": "launch_busy"},
                            detail="This plan is already being researched.")
    # a plan that already counted this month may be retried without using another
    if not (p["sourced"] and p["status"] == "failed"):
        acc = await asyncio.to_thread(pipeline.access, uid)
        if not acc.allowed:
            raise HTTPException(status_code=402, headers={"X-Reason": acc.reason or "plan_required"},
                                detail={"detail": acc.detail, "code": acc.reason, "plan_needed": acc.plan_needed})
    out = await pipeline.begin(uid, plan_id)
    if out is None:
        raise HTTPException(status_code=409, headers={"X-Reason": "launch_busy"},
                            detail="This plan is already being researched.")
    return out


@router.post("/launch/{plan_id}/items/{key}/refresh")
async def refresh_item(plan_id: int, key: str, user: dict = Depends(get_current_user)) -> dict:
    """Search one item's price again (Plus; a few per plan)."""
    from harness.api.routes.brands import need
    from harness.billing import entitlements
    uid = user["user_id"]
    p = await _own(uid, plan_id)
    item = next((it for it in p["items"] if it["key"] == key), None)
    if item is None:
        raise HTTPException(status_code=404, detail="No such item.")
    if not item.get("search"):
        raise HTTPException(status_code=422, detail="This item has no price to look up (a fee or a salary).")
    if p["status"] == "sourcing":
        raise HTTPException(status_code=409, headers={"X-Reason": "launch_busy"},
                            detail="This plan is already being researched.")
    await asyncio.to_thread(need, uid, "launch_sourcing")
    if entitlements.billing_enabled() and not (await asyncio.to_thread(entitlements.standing, uid)).can_spend:
        raise HTTPException(status_code=402, headers={"X-Reason": "insufficient_balance"},
                            detail={"detail": "Your plan's usage for this period is used up.",
                                    "code": "insufficient_balance", "plan_needed": None})
    limit = get_settings().launch_refresh_limit
    if not await asyncio.to_thread(db.use_refresh, uid, plan_id, limit):
        raise HTTPException(status_code=429, headers={"X-Reason": "launch_refresh_limit"},
                            detail=f"Each plan can re-check {limit} prices.")
    await asyncio.to_thread(db.update, uid, plan_id, status="sourcing", error="",
                            progress={"stage": "prices", "done": 0, "total": 1})
    pipeline.start(uid, plan_id, only=[key])
    return await _own(uid, plan_id)


@router.get("/launch/{plan_id}/export")
async def export_plan(plan_id: int, format: str = Query("pdf", pattern="^(pdf|xlsx)$"),
                      user: dict = Depends(get_current_user)) -> Response:
    p = await _own(user["user_id"], plan_id)
    data = await asyncio.to_thread(export.build, p, format)
    name = re.sub(r"[^A-Za-z0-9]+", "-", p["title"]).strip("-")[:60] or "launch-plan"
    media = "application/pdf" if format == "pdf" else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return Response(data, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}.{format}"',
                                                     "Cache-Control": "private, no-store"})


@router.delete("/launch/{plan_id}")
async def delete_plan(plan_id: int, user: dict = Depends(get_current_user)) -> dict:
    if not await asyncio.to_thread(db.hide, user["user_id"], plan_id):
        raise HTTPException(status_code=404, detail="No such plan.")
    return {"ok": True}
