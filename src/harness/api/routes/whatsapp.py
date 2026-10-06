"""WhatsApp routes.

- ``GET /whatsapp/webhook``: Meta's one-time check (hub.verify_token -> hub.challenge).
- ``POST /whatsapp/webhook``: message deliveries. No JWT: authenticated by the
  ``X-Hub-Signature-256`` HMAC with the app secret. Answers 200 at once and
  handles each message in the background (Meta retries slow or failed
  deliveries, and ``whatsapp_inbound`` makes a retry a no-op).
- ``GET/POST/DELETE /whatsapp/link`` (JWT): status, a fresh linking code, unlink.
"""

import asyncio
import json
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse

from harness.api.auth import get_current_user
from harness.config import get_settings
from harness.db import whatsapp as wa_db
from harness.logging import log
from harness.whatsapp import enabled
from harness.whatsapp.inbound import parse, signature_ok

router = APIRouter()
_tasks: set[asyncio.Task] = set()       # keep background handlers referenced until they finish


@router.get("/whatsapp/webhook")
async def verify(request: Request):
    q = request.query_params
    token = get_settings().whatsapp_verify_token
    if q.get("hub.mode") == "subscribe" and token and q.get("hub.verify_token") == token:
        return PlainTextResponse(q.get("hub.challenge", ""))
    raise HTTPException(status_code=403, detail="verification failed")


@router.post("/whatsapp/webhook")
async def webhook(request: Request) -> dict:
    raw = await request.body()
    if not signature_ok(raw, request.headers.get("x-hub-signature-256"), get_settings().whatsapp_app_secret):
        raise HTTPException(status_code=401, detail="bad signature")
    try:
        payload = json.loads(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid JSON") from None
    from harness.whatsapp.service import handle
    messages = parse(payload)
    for msg in messages:
        t = asyncio.create_task(handle(msg))
        _tasks.add(t)
        t.add_done_callback(_tasks.discard)
    if messages:
        log.info("whatsapp delivery", messages=len(messages))
    return {"ok": True}


def _masked(phone: str | None) -> str | None:
    return f"+{phone[:2]} ••••• {phone[-4:]}" if phone and len(phone) > 6 else None


def _wa_link(code: str | None = None) -> str | None:
    number = "".join(ch for ch in (get_settings().whatsapp_business_number or "") if ch.isdigit())
    if not number:
        return None
    return f"https://wa.me/{number}" + (f"?text={quote(f'HANGUL {code}')}" if code else "")


@router.get("/whatsapp/link")
async def link_status(user: dict = Depends(get_current_user)) -> dict:
    if not enabled():
        return {"enabled": False, "linked": False}
    link = await asyncio.to_thread(wa_db.by_user, user["user_id"])
    linked = bool(link and link.linked)
    return {"enabled": True, "linked": linked, "phone": _masked(link.phone) if linked else None,
            "business_number": get_settings().whatsapp_business_number, "chat_link": _wa_link() if linked else None}


@router.post("/whatsapp/link")
async def start_link(user: dict = Depends(get_current_user)) -> dict:
    """A code to send from WhatsApp; the number it comes from becomes this account's."""
    if not enabled():
        raise HTTPException(status_code=503, detail="WhatsApp isn't set up on this server yet.")
    s = get_settings()
    code = await asyncio.to_thread(wa_db.start_link, user["user_id"], s.whatsapp_link_code_ttl_s)
    return {"code": code, "message": f"HANGUL {code}", "expires_in": s.whatsapp_link_code_ttl_s,
            "business_number": s.whatsapp_business_number, "wa_link": _wa_link(code)}


@router.delete("/whatsapp/link")
async def unlink(user: dict = Depends(get_current_user)) -> dict:
    return {"unlinked": await asyncio.to_thread(wa_db.unlink, user["user_id"])}
