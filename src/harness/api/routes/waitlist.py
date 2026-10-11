"""Pre-registration before launch (/join).

Public, no JWT, like /billing/prices: the backend is only reachable through the
web tier, whose relay (web/app/api/waitlist) adds same-origin and a per-address
rate limit. Joining answers the same whether the email is new or already on the
list, so the endpoint can't be used to check who has signed up.
"""

import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from harness.db import waitlist as waitlist_db

router = APIRouter()


class JoinRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    persona: str = Field(default="", max_length=16)
    interest: str = Field(default="", max_length=8)
    source: str = Field(default="", max_length=80)
    trade: str = Field(default="", max_length=16)
    city: str = Field(default="", max_length=80)


@router.post("/waitlist")
async def join(req: JoinRequest) -> dict:
    try:
        await asyncio.to_thread(waitlist_db.join, req.email, req.persona, req.interest, req.source,
                                req.trade, req.city)
    except ValueError as e:
        field = str(e)
        detail = {"email": "That doesn't look like an email address.",
                  "persona": "Pick one of the options.",
                  "interest": "Pick Free, Plus or Pro.",
                  "trade": "Pick one of the kinds of business."}.get(field, "Check the form and try again.")
        raise HTTPException(status_code=422, detail=detail)
    return {"ok": True, "total": await asyncio.to_thread(waitlist_db.total)}


@router.get("/waitlist/count")
async def count() -> dict:
    return {"total": await asyncio.to_thread(waitlist_db.total)}
