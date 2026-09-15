import asyncio
import json
import time
from pydantic import BaseModel, Field

from harness.providers.base import Provider
from harness.tools.openai_spec import to_openai_tool
from harness.tools.registry import ToolRegistry
from harness.logging import log

from harness.policy.guarded import guarded_dispatch
from harness.policy.policy import ToolPolicy
from harness.policy.audit import AuditLog
from harness.policy.budget import Budget
from harness.policy.tiers import Decision

from harness.checkpoint.checkpoint import Checkpoint
from harness.checkpoint.store import CheckpointStore
from harness.checkpoint.idempotency import call_key

from harness.obs.tracing import Trace

# Strong refs to in-flight checkpoint writes (asyncio holds tasks weakly).
_pending_saves: set[asyncio.Task] = set()


RETRIEVAL_TOOLS = {"search_docs", "filesystem__read_text_file", "filesystem__read_file"}

PREVIEW_CHARS = 240


def _preview(content: str) -> str:
    """A short, single-line excerpt of a tool result, safe to show in the UI."""
    flat = " ".join((content or "").split())
    return flat[:PREVIEW_CHARS] + ("…" if len(flat) > PREVIEW_CHARS else "")


class AgentResult(BaseModel):
    answer: str
    steps: int
    stopped_reason: str
    input_tokens: int
    output_tokens: int
    retrieved_context: str = ""
    tools_used: list[str] = Field(default_factory=list)
    safety_blocked: list[str] = Field(default_factory=list)
    budget_used: dict = Field(default_factory=dict)
    resumed_from_step: int = 0
    pending_tool: dict | None = None



async def run_agent(
    *,
    question: str,
    prompt_text: str,
    registry: ToolRegistry,
    provider: Provider,
    policy: ToolPolicy,
    audit: AuditLog,
    store: CheckpointStore,
    thread_id: str,
    trace: Trace,
    approved_action: dict | None = None,
    force_tool_use: bool = False,
    max_steps: int = 20,
    max_tokens: int = 50_000,
    on_event=None,
    user_id: str | None = None,
    history: list[dict] | None = None,
) -> AgentResult:
    """Run the tool-calling loop.

    on_event: optional callback invoked with a dict describing what the agent
    is doing right now, so a caller (the SSE route) can broadcast progress
    while the run is still going. Event types:
      step        {step}
      text_start  {block}                        a turn began producing text
      text_delta  {block, text}                  one token of that text
      text_end    {block}
      tool_call   {id, name, arguments, step}    model decided to call a tool
      tool_result {id, name, ok, preview, ms, cached}

    user_id is stamped on the checkpoint so /approve can verify ownership.
    history is prior conversation turns ({role, content}, user/assistant only)
    placed between the system prompt and the new question on a *fresh* run,
    so follow-up questions have context. It is ignored when resuming.
    """
    # CheckpointStore is sync SQLAlchemy against a (possibly remote) Postgres,
    # so every call goes through a worker thread rather than blocking the loop.
    cp = await asyncio.to_thread(store.load, thread_id) or Checkpoint(
        thread_id=thread_id,
        user_id=user_id,
        message=[
            {"role": "system", "content": prompt_text},
            *[{"role": m["role"], "content": m["content"]} for m in (history or [])],
            {"role": "user", "content": question},
        ],
    )
    if cp.user_id is None:
        cp.user_id = user_id
    messages = cp.message

    # Checkpoint writes are chained so they land in order, but only the
    # pending_approval write is awaited -- /approve has to find it. Mid-run and
    # final writes exist for resume/forensics, nothing on the response path
    # reads them, so the answer is not held behind a DB round-trip.
    last_save: asyncio.Task | None = None

    async def persist(wait: bool = False) -> None:
        nonlocal last_save
        snapshot = cp.model_copy(deep=True)
        prev = last_save

        async def _write() -> None:
            if prev is not None:
                await prev
            try:
                await asyncio.to_thread(store.save, snapshot)
            except Exception as e:  # noqa: BLE001
                log.warning("checkpoint save failed", thread_id=thread_id, error=str(e))

        last_save = asyncio.create_task(_write())
        _pending_saves.add(last_save)
        last_save.add_done_callback(_pending_saves.discard)
        if wait:
            await last_save

    def emit(kind: str, **payload) -> None:
        if on_event is not None:
            on_event({"type": kind, **payload})

    tools = [to_openai_tool(t) for t in registry.list()]
    total_in = total_out = 0
    retrieved: list[str] = []
    tools_used: list[str] = []
    safety_blocked: list[str] = []
    resumed_from = cp.step
    first_step = cp.step + 1   # the step number of the very first iteration

    budget = Budget(max_steps=max_steps, max_tokens=max_tokens)

    def _budget_snapshot() -> dict:
        return {
            "steps": budget.steps,
            "max_steps": max_steps,
            "tokens": budget.tokens,
            "max_tokens": max_tokens,
        }

    async def _run_one_tool(tc, is_approved: bool = False) -> str:
        """Dispatch a single tool call, emit a result event, return its content."""
        key = call_key(thread_id, tc.name, tc.arguments)
        if key in cp.completed_calls:
            content = cp.completed_calls[key]
            emit("tool_result", id=tc.id, name=tc.name, ok=True,
                 preview=_preview(content), ms=0, cached=True)
            return content

        started = time.perf_counter()
        ok = True
        with trace.span("gen_ai.tool.execute", **{"gen_ai.tool.name": tc.name}):
            try:
                result = await guarded_dispatch(registry.get(tc.name), tc.arguments,
                                                policy, audit, approved=is_approved)
                content = result.content
            except KeyError:
                content = f"Error: unknown tool {tc.name}"
                ok = False
            except Exception as e:
                content = (f"Error: tool '{tc.name}' failed ({type(e).__name__}). "
                           "Do not retry the same call; try a different approach "
                           "or answer with what you have.")
                ok = False
        cp.completed_calls[key] = content
        emit("tool_result", id=tc.id, name=tc.name,
             ok=ok and not content.startswith("Error"),
             preview=_preview(content),
             ms=int((time.perf_counter() - started) * 1000), cached=False)
        return content

    with trace.span("agent.run", question=question):
        for step in range(cp.step + 1, max_steps + 1):
            reason = budget.exceeded()
            if reason:
                cp.status = "done"
                await persist()
                return AgentResult(
                    answer=f"Stopped: {reason}.", steps=step - 1,
                    stopped_reason="budget_exceeded",
                    input_tokens=total_in, output_tokens=total_out,
                    retrieved_context="\n\n".join(retrieved),
                    tools_used=tools_used, safety_blocked=safety_blocked,
                    budget_used=_budget_snapshot(), resumed_from_step=resumed_from,
                )

            with trace.span("gen_ai.chat",
                            **{"gen_ai.request.model": provider.model}) as sp:
                
                tc_choice = "required" if (force_tool_use and step == first_step) else None
                emit("step", step=step)

                streamable = on_event is not None and hasattr(provider, "chat_stream")
                if streamable:
                    # Stream EVERY turn, not just the last one: the text a turn
                    # produces before its tool calls is the agent narrating what
                    # it is about to do, and that is exactly what we broadcast.
                    turn = None
                    block = f"{thread_id}:{step}"
                    opened = False
                    async for kind, payload in provider.chat_stream(
                            messages, tools, tool_choice=tc_choice):
                        if kind == "token":
                            if not opened:
                                emit("text_start", block=block)
                                opened = True
                            emit("text_delta", block=block, text=payload)
                        else:
                            turn = payload
                    if opened:
                        emit("text_end", block=block)
                else:
                    turn = await provider.chat(messages, tools, tool_choice=tc_choice)
            sp.attributes["gen_ai.usage.input_tokens"] = turn.input_tokens
            sp.attributes["gen_ai.usage.output_tokens"] = turn.output_tokens

            total_in += turn.input_tokens
            total_out += turn.output_tokens
            budget.add(steps=1, tokens=turn.input_tokens + turn.output_tokens)

            if not turn.tool_calls:
                cp.status = "done"
                cp.step = step
                await persist()
                return AgentResult(
                    answer=turn.text or "", steps=step, stopped_reason="answered",
                    input_tokens=total_in, output_tokens=total_out,
                    retrieved_context="\n\n".join(retrieved),
                    tools_used=tools_used, safety_blocked=safety_blocked,
                    budget_used=_budget_snapshot(), resumed_from_step=resumed_from,
                )

            messages.append({
                "role": "assistant",
                "content": turn.text or "",
                "tool_calls": [
                    {
                        "id": tc.id, "type": "function",
                        "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                    } for tc in turn.tool_calls
                ],
            })

            for tc in turn.tool_calls:
                if tc.name not in tools_used:
                    tools_used.append(tc.name)
                emit("tool_call", id=tc.id, name=tc.name,
                     arguments=tc.arguments, step=step)

            # find the first tool call that needs approval (and isn't pre-approved)
            pending_idx = None
            for i, tc in enumerate(turn.tool_calls):
                is_approved = (approved_action is not None
                               and approved_action.get("tool_call_id") == tc.id)
                if policy.decide(tc.name) == Decision.NEEDS_APPROVAL and not is_approved:
                    pending_idx = i
                    break

            if pending_idx is not None:
                # execute tool calls BEFORE the pending one (real responses)
                for tc in turn.tool_calls[:pending_idx]:
                    content = await _run_one_tool(tc)
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": content})

                # the pending tool: save it + a placeholder response (keeps history valid)
                p = turn.tool_calls[pending_idx]
                cp.pending_tool = {"name": p.name, "arguments": p.arguments, "tool_call_id": p.id}
                emit("tool_result", id=p.id, name=p.name, ok=True,
                     preview="Waiting for your approval.", ms=0, cached=False)
                messages.append({"role": "tool", "tool_call_id": p.id,
                                 "content": "[awaiting human approval]"})

                # placeholder responses for any tool calls AFTER the pending one
                for tc in turn.tool_calls[pending_idx + 1:]:
                    emit("tool_result", id=tc.id, name=tc.name, ok=False,
                         preview="Not run — an earlier call needs approval.",
                         ms=0, cached=False)
                    messages.append({"role": "tool", "tool_call_id": tc.id,
                                     "content": "[not executed — pending earlier approval]"})

                cp.message = messages
                cp.step = step
                cp.status = "pending_approval"
                await persist(wait=True)
                log.info("paused for approval", tool=p.name, args=p.arguments)
                return AgentResult(
                    answer=f"The agent wants to run '{p.name}'. Your approval is needed.",
                    steps=step, stopped_reason="pending_approval",
                    input_tokens=total_in, output_tokens=total_out,
                    retrieved_context="\n\n".join(retrieved),
                    tools_used=tools_used, safety_blocked=[p.name],
                    budget_used=_budget_snapshot(), resumed_from_step=resumed_from,
                    pending_tool=cp.pending_tool,
                )

            # no approval needed this turn — run every tool normally
            for tc in turn.tool_calls:
                is_approved = (approved_action is not None
                               and approved_action.get("tool_call_id") == tc.id)
                content = await _run_one_tool(tc, is_approved=is_approved)

                if "approval" in content.lower() or "not executed" in content.lower():
                    if tc.name not in safety_blocked:
                        safety_blocked.append(tc.name)
                if tc.name in RETRIEVAL_TOOLS and not content.startswith(("Invalid", "Error", "Tool")):
                    retrieved.append(content)
                log.info("tool call", step=step, tool=tc.name, args=tc.arguments, result=content[:150])
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": content})

            approved_action = None
            cp.message = messages
            cp.step = step
            cp.pending_tool = None
            await persist()

    cp.status = "done"
    await persist()
    return AgentResult(
        answer="Stopped before finishing: reached the step limit.",
        steps=max_steps, stopped_reason="max_steps",
        input_tokens=total_in, output_tokens=total_out,
        retrieved_context="\n\n".join(retrieved),
        tools_used=tools_used, safety_blocked=safety_blocked,
        budget_used=_budget_snapshot(), resumed_from_step=resumed_from,
    )
