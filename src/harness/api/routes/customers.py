"""/customers: the shop's own customer list (db/customers.py), on every plan.

A foreign id is a 404, like a missing one. ``GET /customers`` also returns the
birthdays in the coming week and the regulars who haven't been in for a while,
so the page needs one request.
"""

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from harness.api.auth import get_current_user
from harness.db import customers as db
from harness.sales.service import local_today

router = APIRouter()

PROBLEMS = {"name": "Give the customer a name.", "phone": "That doesn't look like a phone number.",
            "birthday": "That birthday isn't a real date (try 12/03 or 12 March)."}


class CustomerIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    phone: str = Field(default="", max_length=24)
    birthday: str = Field(default="", max_length=24)
    note: str = Field(default="", max_length=200)
    business_id: int | None = None


class CustomerPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    phone: str | None = Field(default=None, max_length=24)          # "" clears it
    birthday: str | None = Field(default=None, max_length=24)       # "" clears it
    note: str | None = Field(default=None, max_length=200)


def _422(e: ValueError) -> HTTPException:
    return HTTPException(status_code=422, detail=PROBLEMS.get(str(e), "Check the details and try again."))


@router.get("/customers")
async def list_customers(q: str = "", user: dict = Depends(get_current_user)) -> dict:
    uid = user["user_id"]
    today = await asyncio.to_thread(local_today, uid)
    rows, total, birthdays, away = await asyncio.gather(
        asyncio.to_thread(db.find, uid, q[:80], 200), asyncio.to_thread(db.count, uid),
        asyncio.to_thread(db.upcoming_birthdays, uid, today, 7), asyncio.to_thread(db.lapsed, uid, today))
    return {"customers": rows, "total": total, "birthdays": birthdays, "lapsed": away, "today": today.isoformat()}


@router.post("/customers")
async def add_customer(body: CustomerIn, user: dict = Depends(get_current_user)) -> dict:
    try:
        row, created = await asyncio.to_thread(lambda: db.add(user["user_id"], **body.model_dump()))
    except ValueError as e:
        raise _422(e) from e
    except db.TooMany as e:
        raise HTTPException(status_code=422, detail=f"The list holds up to {db.MAX_PER_USER:,} customers.") from e
    return {**row, "created": created}


@router.patch("/customers/{customer_id}")
async def edit_customer(customer_id: int, body: CustomerPatch, user: dict = Depends(get_current_user)) -> dict:
    try:
        row = await asyncio.to_thread(lambda: db.update(user["user_id"], customer_id, **body.model_dump(exclude_unset=True)))
    except ValueError as e:
        raise _422(e) from e
    if row is None:
        raise HTTPException(status_code=404, detail="No such customer.")
    return row


@router.delete("/customers/{customer_id}")
async def remove_customer(customer_id: int, user: dict = Depends(get_current_user)) -> dict:
    if not await asyncio.to_thread(db.remove, user["user_id"], customer_id):
        raise HTTPException(status_code=404, detail="No such customer.")
    return {"removed": True}


@router.post("/customers/{customer_id}/visit")
async def customer_visited(customer_id: int, user: dict = Depends(get_current_user)) -> dict:
    uid = user["user_id"]
    today = await asyncio.to_thread(local_today, uid)
    row = await asyncio.to_thread(db.visit, uid, customer_id, today)
    if row is None:
        raise HTTPException(status_code=404, detail="No such customer.")
    return row
