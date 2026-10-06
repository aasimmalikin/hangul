"""GET/POST /approval-links/{token}: approve a waiting action from an email or
notification without signing in (see harness.approval_links for why that is safe).

No JWT: the signed token is the credential, and it only ever reaches the one run it
names. GET shows the action (safe for mail scanners that prefetch links); POST
decides it through the /approve route function, so the plan check, ownership,
expiry and claim-once rules are exactly the app's.
"""

import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from harness import approval_links
from harness.approval_card import card
from harness.logging import log

router = APIRouter()


class Decision(BaseModel):
    decision: str


def _verify(token: str) -> tuple[str, str]:
    try:
        return approval_links.read(token)
    except approval_links.LinkError as e:
        # one answer for forged, mangled and expired links: nothing to probe
        raise HTTPException(status_code=410, detail="This link has expired or isn't valid.",
                            headers={"X-Reason": "link_invalid"}) from e


def _asked(cp) -> str:
    """The words the run was started with (the scheduled task's question)."""
    for m in cp.message or []:
        if m.get("role") == "user" and isinstance(m.get("content"), str):
            return m["content"][:600]
    return ""


@router.get("/approval-links/{token}")
async def show(token: str) -> dict:
    from harness.api.routes.approve import _store
    run_id, user_id = _verify(token)
    cp = await asyncio.to_thread(_store.load, run_id)
    if cp is None or str(cp.user_id) != user_id:
        raise HTTPException(status_code=410, detail="This link has expired or isn't valid.",
                            headers={"X-Reason": "link_invalid"})
    state = {"pending_approval": "waiting", "expired": "expired"}.get(cp.status, "decided")
    return {"state": state, "asked": _asked(cp),
            "card": card(cp.pending_tool) if state == "waiting" else None,
            "conversation_id": getattr(cp, "conversation_id", None)}


@router.post("/approval-links/{token}")
async def decide(token: str, body: Decision) -> dict:
    from harness.api.routes.approve import ApproveRequest, approve
    if body.decision not in ("approve", "reject"):
        raise HTTPException(status_code=422, detail="decision must be 'approve' or 'reject'.")
    run_id, user_id = _verify(token)
    try:
        resp = await approve(ApproveRequest(approval_id=run_id, decision=body.decision), user={"user_id": user_id})
    except HTTPException as e:
        if e.status_code in (404, 409):      # decided already (here, the app, WhatsApp) or expired
            reason = (e.headers or {}).get("X-Reason", "")
            return {"state": "expired" if reason == "approval_expired" else "decided", "answer": ""}
        raise
    log.info("approved by link", run_id=run_id, user_id=user_id, decision=body.decision)
    return {"state": "approved" if body.decision == "approve" else "rejected", "answer": resp.answer,
            "waiting_again": bool(resp.pending_tool), "conversation_id": resp.conversation_id}
