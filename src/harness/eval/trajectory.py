"""What the agent *did* on one run, captured from the loop's events.

The QA evals only look at the final answer; the agent evals (tool selection,
efficiency, approval compliance) need the ordered tool calls with their
arguments, which the loop already emits through ``on_event``. ``capture()``
turns that stream into a ``Trajectory``."""

import time

from pydantic import BaseModel, Field


class ToolCall(BaseModel):
    step: int
    name: str
    arguments: dict = Field(default_factory=dict)
    ok: bool | None = None          # None = never got a result (paused / not run)
    ms: int = 0
    cached: bool = False
    preview: str = ""
    result: str = ""                # full tool output (from the checkpoint), for the judge

class Trajectory(BaseModel):
    calls: list[ToolCall] = Field(default_factory=list)
    steps: int = 0
    stopped_reason: str = ""
    pending_tool: str | None = None     # a DESTRUCTIVE/ELICIT call the run paused on
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    cost_usd: float = 0.0
    answer: str = ""
    security_events: list[dict] = Field(default_factory=list)

    @property
    def tool_names(self) -> list[str]:
        return [c.name for c in self.calls]

    @property
    def tool_set(self) -> set[str]:
        return set(self.tool_names)

    def repeated_calls(self) -> int:
        """Identical (name, arguments) pairs seen more than once: the loop's
        own idempotency cache serves them, but the model still asked."""
        seen: set[str] = set()
        dup = 0
        for c in self.calls:
            key = c.name + "|" + _canon(c.arguments)
            if key in seen:
                dup += 1
            seen.add(key)
        return dup

def _canon(args: dict) -> str:
    import json
    try:
        return json.dumps(args, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return repr(args)

class TrajectoryRecorder:
    """Pass ``.on_event`` to ``run_agent(on_event=...)``, then ``.finish(result)``."""

    def __init__(self) -> None:
        self.traj = Trajectory()
        self._by_id: dict[str, ToolCall] = {}
        self._started = time.perf_counter()

    def on_event(self, ev: dict) -> None:
        kind = ev.get("type")
        if kind == "step":
            self.traj.steps = max(self.traj.steps, int(ev.get("step", 0)))
        elif kind == "tool_call":
            call = ToolCall(step=int(ev.get("step", 0)), name=ev["name"],
                            arguments=dict(ev.get("arguments") or {}))
            self.traj.calls.append(call)
            self._by_id[ev["id"]] = call
        elif kind == "security":
            self.traj.security_events.append({k: v for k, v in ev.items() if k not in ("type", "answer")})
        elif kind == "tool_result":
            call = self._by_id.get(ev.get("id"))
            if call is not None:
                call.ok = bool(ev.get("ok"))
                call.ms = int(ev.get("ms", 0))
                call.cached = bool(ev.get("cached"))
                call.preview = str(ev.get("preview", ""))

    def attach_results(self, thread_id: str, completed_calls: dict[str, str]) -> None:
        """Fill ``ToolCall.result`` from the checkpoint's idempotency cache,
        which holds the full output the model saw (events only carry a preview)."""
        from harness.checkpoint.idempotency import call_key
        for c in self.traj.calls:
            c.result = completed_calls.get(call_key(thread_id, c.name, c.arguments), "")

    def finish(self, result, model: str) -> Trajectory:
        from harness.obs.tracing import cost_usd
        t = self.traj
        t.latency_ms = int((time.perf_counter() - self._started) * 1000)
        t.stopped_reason = result.stopped_reason
        t.pending_tool = (result.pending_tool or {}).get("name")
        t.input_tokens = result.input_tokens
        t.output_tokens = result.output_tokens
        t.cost_usd = cost_usd(model, result.input_tokens, result.output_tokens)
        t.answer = result.answer
        if result.steps:
            t.steps = max(t.steps, result.steps)
        return t

