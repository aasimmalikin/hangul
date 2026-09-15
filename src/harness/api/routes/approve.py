"""POST /approve — resume a paused run after a human decision."""

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from harness.agent.loop import run_agent
from harness.logging import log
from harness.providers import get_provider
from harness.prompts.registry import get_prompt
from harness.api.session import get_session_id
from harness.api.auth import get_current_user
from harness.obs.tracing import Trace, cost_usd
from harness.policy.guarded import guarded_dispatch

from harness.api.routes.ask import (
    _store, _audit, _policy, _trace_store, _registry, AskResponse,
)
from harness.tools.registry import ToolRegistry
from harness.tools.builtin.calculator import CALCULATOR_TOOL
from harness.tools.builtin.web_search import WEB_SEARCH_TOOL
from harness.tools.builtin.ask_user import ASK_USER_TOOL
from harness.tools.builtin.search_docs_session import make_search_docs_tool
from harness.tools.builtin.filesystem_session import wrap_filesystem_tool

router = APIRouter()


class ApproveRequest(BaseModel):
    approval_id: str
    decision: str
    choice: str | None = None


def _build_session_registry(user_id: str) -> ToolRegistry:
    reg = ToolRegistry()
    reg.registry(make_search_docs_tool(user_id))
    reg.registry(CALCULATOR_TOOL)
    reg.registry(WEB_SEARCH_TOOL)
    reg.registry(ASK_USER_TOOL)
    for t in _registry.list():
        if t.name.startswith("filesystem__"):
            reg.registry(wrap_filesystem_tool(t, user_id))
    return reg


def _replace_placeholder(messages: list[dict], tool_call_id: str, content: str) -> None:
    """Overwrite the [awaiting human approval] placeholder with the real result."""
    for m in messages:
        if m.get("role") == "tool" and m.get("tool_call_id") == tool_call_id:
            m["content"] = content
            return
    # if not found (shouldn't happen), append it
    messages.append({"role": "tool", "tool_call_id": tool_call_id, "content": content})


@router.post("/approve", response_model=AskResponse)
async def approve(req: ApproveRequest, user: dict = Depends(get_current_user)) -> AskResponse:
    if req.decision not in ("approve", "reject"):
        raise HTTPException(status_code=422, detail="decision must be 'approve' or 'reject'.")

    # One conditional UPDATE both checks that the caller owns this run and
    # takes the pending action off it, so a retried or double-clicked approve
    # cannot execute the tool twice, and a foreign run id reads as not found.
    cp = await asyncio.to_thread(_store.claim_pending, req.approval_id, user["user_id"])
    if cp is None:
        raise HTTPException(status_code=404, detail="No pending action for that approval id.")

    pending = cp.pending_tool
    model = get_provider().model
    prompt_version = get_prompt("system_agent")
    session_registry = _build_session_registry(user["user_id"])

    # ask_user is a clarification, not an action: the run should carry on with
    # the original task, not summarise. Every other tool just gets confirmed.
    follow_up = "Briefly confirm what was just done, in one sentence."

    if pending["name"] == "ask_user":
        content = f"The user chose: {req.choice}"
        follow_up = ("The user answered your clarifying question. Continue the "
                     "original request using their choice. Do not ask again.")
        log.info("user answered clarification", choice = req.choice)

    elif req.decision == "reject":
        content = (f"The user REJECTED the action '{pending['name']}'. "
                   f"Do not attempt it. Continue and answer without it.")
        log.info("action rejected", tool=pending["name"])
    else:
        try:
            args = dict(pending["arguments"])
            # FORCE the path inside this session's folder, whatever the agent proposed
            if "path" in args and pending["name"].startswith("filesystem__"):
                from pathlib import Path
                session_dir = (Path("data/sessions") / user["user_id"]).resolve()
                session_dir.mkdir(parents=True, exist_ok=True)
                filename = Path(args["path"]).name        # keep only the filename part
                args["path"] = str(session_dir / filename)
                log.info("forced path", original=pending["arguments"].get("path"), forced=args["path"])

            tool = session_registry.get(pending["name"])
            result = await guarded_dispatch(tool, args, _policy, _audit, approved=True)
            content = result.content
            log.info("action approved and executed", tool=pending["name"], result=content[:150])
        except Exception as e:  # noqa: BLE001
            content = f"Error executing approved action: {e}"
            log.warning("approved action failed", error=str(e))

    # replace the placeholder response with the real outcome (claim_pending
    # already cleared pending_tool and set status back to running)
    _replace_placeholder(cp.message, pending["tool_call_id"], content)
    cp.pending_tool = None
    cp.status = "running"
    await asyncio.to_thread(_store.save, cp)

    trace = Trace(trace_id=req.approval_id)
    result = await run_agent(
        question=follow_up,
        prompt_text=prompt_version.text,
        registry=session_registry,
        provider=get_provider(),
        policy=_policy,
        audit=_audit,
        store=_store,
        thread_id=req.approval_id,
        trace=trace,
        user_id=user["user_id"],
    )

    _trace_store.add(trace, model)
    summary = trace.summary()
    run_cost = cost_usd(model, summary["input_tokens"], summary["output_tokens"])

    return AskResponse(
        answer=result.answer,
        run_id=req.approval_id,
        prompt_version=prompt_version.version,
        steps=result.steps,
        stopped_reason=result.stopped_reason,
        cached=False,
        tools_used=result.tools_used,
        safety_blocked=result.safety_blocked,
        budget_used=result.budget_used,
        cost_usd=run_cost,
        resumed_from_step=result.resumed_from_step,
        pending_tool=result.pending_tool,
    )