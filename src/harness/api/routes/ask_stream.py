import asyncio
import json

from fastapi import Request, APIRouter, Depends, HTTPException
from sse_starlette.sse import EventSourceResponse

from harness.api.auth import get_current_user
from harness.api.concurrency import run_slot
from harness.api.routes.ask import AskRequest, _build_and_run

router = APIRouter()

# Progress events the agent emits mid-run. Each is forwarded verbatim as a
# named SSE event, so the browser sees what the agent is doing as it happens.
AGENT_EVENTS = {"step", "text_start", "text_delta", "text_end",
                "tool_pending", "tool_args_delta", "tool_call", "tool_result"}


@router.post("/ask/stream")
async def ask_stream(req: AskRequest, request: Request,
                     user: dict = Depends(get_current_user)):
    user_id = user["user_id"]

    # Bridge between the agent (producing events) and the SSE generator
    # (sending them). The agent runs as a background task and pushes events
    # onto this queue via the on_event callback; the generator drains it live.
    queue: asyncio.Queue = asyncio.Queue()

    def on_event(event: dict) -> None:
        queue.put_nowait(("agent", event))

    async def run_and_signal():
        """Run the agent in the background; put the final outcome (or error)
        on the queue when done so the generator knows to stop."""
        try:
            async with run_slot(user_id):
                outcome = await _build_and_run(req, user_id, on_event=on_event)
            await queue.put(("outcome", outcome))
        except HTTPException as e:
            await queue.put(("error", e.detail))
        except Exception as e:  # noqa: BLE001
            await queue.put(("error", str(e)))

    async def event_generator():
        task = asyncio.create_task(run_and_signal())
        open_blocks: list[str] = []
        streamed_text = False
        try:
            while True:
                if await request.is_disconnected():
                    # Tab closed / navigated away / network gone: stop paying
                    # for tokens nobody will read. The checkpoint keeps what
                    # was done so far.
                    task.cancel()
                    return

                # Wake up periodically even when the agent is quiet so the
                # disconnect check above runs during a long model call.
                try:
                    kind, payload = await asyncio.wait_for(queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue

                if kind == "agent":
                    etype = payload["type"]
                    if etype not in AGENT_EVENTS:
                        continue
                    if etype == "text_start":
                        open_blocks.append(payload["block"])
                    elif etype == "text_delta":
                        streamed_text = True
                    elif etype == "text_end":
                        if payload["block"] in open_blocks:
                            open_blocks.remove(payload["block"])
                    yield {"event": etype, "data": json.dumps(payload)}

                elif kind == "error":
                    yield {"event": "error", "data": json.dumps({"message": payload})}
                    return

                elif kind == "outcome":
                    outcome = payload
                    r = outcome.result

                    # Close any text block the run left open (cancelled turn).
                    for block in open_blocks:
                        yield {"event": "text_end", "data": json.dumps({"block": block})}
                    open_blocks = []

                    if r.pending_tool:
                        yield {"event": "approval_required", "data": json.dumps({
                            **r.pending_tool,
                            "run_id": outcome.run.run_id,
                        })}
                    elif not streamed_text and r.answer:
                        # Non-streaming path (provider without chat_stream, or a
                        # budget/step-limit stop): send the answer as one block
                        # so the user still sees it.
                        block = f"{outcome.run.run_id}:final"
                        yield {"event": "text_start", "data": json.dumps({"block": block})}
                        yield {"event": "text_delta",
                               "data": json.dumps({"block": block, "text": r.answer})}
                        yield {"event": "text_end", "data": json.dumps({"block": block})}

                    yield {"event": "done", "data": json.dumps({
                        "steps": r.steps,
                        "run_id": outcome.run.run_id,
                        "cost_usd": outcome.run_cost,
                        "tools_used": r.tools_used,
                    })}
                    return
        finally:
            if not task.done():
                task.cancel()

    return EventSourceResponse(event_generator())
