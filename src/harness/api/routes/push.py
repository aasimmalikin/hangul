"""Notifications on this device (Web Push, harness/push.py).

- ``GET /push`` (JWT): is push set up on the server, its public key, and how
  many devices this user has on (``?endpoint=`` also says whether that one is).
- ``POST /push/subscribe``: the browser's PushSubscription; only the browsers'
  own push services are accepted as endpoints.
- ``POST /push/unsubscribe``: turn it off on one device.
- ``POST /push/test``: send "notifications are on" to every device.
"""

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from harness import push
from harness.api.auth import get_current_user
from harness.db import push as push_db

router = APIRouter()


class Keys(BaseModel):
    p256dh: str = Field(min_length=20, max_length=255)
    auth: str = Field(min_length=8, max_length=64)


class Subscription(BaseModel):
    endpoint: str = Field(max_length=1024)
    keys: Keys


class Endpoint(BaseModel):
    endpoint: str = Field(max_length=1024)


@router.get("/push")
async def status(endpoint: str | None = None, user: dict = Depends(get_current_user)) -> dict:
    if not push.enabled():
        return {"enabled": False, "public_key": None, "devices": 0, "this_device": False}
    uid = user["user_id"]
    return {"enabled": True, "public_key": push.public_key(),
            "devices": await asyncio.to_thread(push_db.count, uid),
            "this_device": bool(endpoint) and await asyncio.to_thread(push_db.has, uid, endpoint)}


@router.post("/push/subscribe")
async def subscribe(body: Subscription, request: Request, user: dict = Depends(get_current_user)) -> dict:
    if not push.enabled():
        raise HTTPException(status_code=503, detail="Notifications aren't set up on this server yet.")
    if not push.endpoint_ok(body.endpoint):
        raise HTTPException(status_code=422, detail="That isn't a browser push address.")
    await asyncio.to_thread(push_db.save, user["user_id"], body.endpoint, body.keys.p256dh, body.keys.auth,
                            request.headers.get("user-agent"))
    return {"subscribed": True}


@router.post("/push/unsubscribe")
async def unsubscribe(body: Endpoint, user: dict = Depends(get_current_user)) -> dict:
    return {"unsubscribed": await asyncio.to_thread(push_db.remove, user["user_id"], body.endpoint)}


@router.post("/push/test")
async def test(user: dict = Depends(get_current_user)) -> dict:
    if not push.enabled():
        raise HTTPException(status_code=503, detail="Notifications aren't set up on this server yet.")
    sent = await push.send(user["user_id"], "Hangul", "Notifications are on. Your reminders will show up here.",
                           url="/", tag="push-test")
    return {"sent": sent}
