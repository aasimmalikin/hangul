"""Guarantees that matter once several people use the agent at once:

- a run can only be resumed (approved) by the user who started it
- a double-clicked / retried approve executes the tool once
- one user cannot hold more than N runs in flight
- request bodies are bounded, and conversation history reaches the model
- anything that changes the answer changes the cache key
"""
import asyncio
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from harness.agent import loop as loop_module
from harness.agent.loop import run_agent, AgentResult
from harness.api import concurrency
from harness.api.auth import get_current_user
from harness.api.routes import approve as approve_route
from harness.api.routes.ask import AskRequest
from harness.cache.keys import answer_key
from harness.checkpoint.checkpoint import Checkpoint
from harness.obs.tracing import Trace
from harness.policy.audit import AuditLog
from harness.policy.policy import ToolPolicy
from harness.providers.base import AssistantTurn
from harness.tools.registry import ToolRegistry


# ---------------------------------------------------------------- fakes

class FakeStore:
    """In-memory CheckpointStore with the same claim semantics as Postgres."""
    def __init__(self):
        self.rows: dict[str, Checkpoint] = {}
        self.claims = 0

    def load(self, thread_id):
        return self.rows.get(thread_id)

    def save(self, cp):
        self.rows[cp.thread_id] = cp.model_copy(deep=True)

    def claim_pending(self, thread_id, user_id):
        cp = self.rows.get(thread_id)
        if cp is None or cp.user_id != user_id or cp.pending_tool is None:
            return None
        self.claims += 1
        claimed = cp.model_copy(deep=True)   # caller gets the action…
        cp.pending_tool = None               # …the row no longer has it
        cp.status = "running"
        return claimed


class EchoProvider:
    """Answers immediately with the messages it was given, so a test can see
    exactly what context reached the model."""
    model = "fake-model"

    def __init__(self):
        self.seen: list[list[dict]] = []

    async def chat(self, messages, tools, tool_choice=None):
        self.seen.append([dict(m) for m in messages])
        return AssistantTurn(text="ok", input_tokens=1, output_tokens=1)


def pending_checkpoint(thread_id: str, user_id: str) -> Checkpoint:
    return Checkpoint(
        thread_id=thread_id, user_id=user_id, step=1, status="pending_approval",
        pending_tool={"name": "filesystem__write_file",
                      "arguments": {"path": "x.txt", "content": "hi"},
                      "tool_call_id": "call_1"},
        message=[
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "write x"},
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "call_1", "type": "function",
                 "function": {"name": "filesystem__write_file", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "call_1", "content": "[awaiting human approval]"},
        ],
    )


@pytest.fixture
def approve_app(monkeypatch):
    """The /approve route wired to fakes: no DB, no model, no MCP."""
    store = FakeStore()
    executed: list[str] = []

    async def fake_dispatch(tool, args, policy, audit, approved=False):
        executed.append(tool)
        class R:  # noqa: D401
            content = "written"
        return R()

    async def fake_run_agent(**kw):
        return AgentResult(answer="done", steps=2, stopped_reason="answered",
                           input_tokens=1, output_tokens=1)

    class FakeRegistry:
        def get(self, name):
            return name

    class FakeProvider:
        model = "fake-model"

    class FakePrompt:
        text = "sys"
        version = "v1"

    monkeypatch.setattr(approve_route, "_store", store)
    monkeypatch.setattr(approve_route, "guarded_dispatch", fake_dispatch)
    monkeypatch.setattr(approve_route, "run_agent", fake_run_agent)
    monkeypatch.setattr(approve_route, "_build_session_registry", lambda uid: FakeRegistry())
    monkeypatch.setattr(approve_route, "get_provider", lambda: FakeProvider())
    monkeypatch.setattr(approve_route, "get_prompt", lambda name: FakePrompt())
    monkeypatch.setattr(approve_route, "_trace_store", type("T", (), {"add": lambda *a: None})())
    monkeypatch.setattr(approve_route, "cost_usd", lambda *a: 0.0)

    app = FastAPI()
    app.include_router(approve_route.router)
    current = {"user_id": "alice", "role": "user"}
    app.dependency_overrides[get_current_user] = lambda: current
    return app, store, executed, current


# ------------------------------------------------------------ approve

def test_approve_by_owner_executes_once(approve_app):
    app, store, executed, _ = approve_app
    store.save(pending_checkpoint("run-1", "alice"))
    c = TestClient(app)

    r = c.post("/approve", json={"approval_id": "run-1", "decision": "approve"})
    assert r.status_code == 200, r.text
    assert executed == ["filesystem__write_file"]

    # The second click (or a retried request) finds nothing pending.
    r2 = c.post("/approve", json={"approval_id": "run-1", "decision": "approve"})
    assert r2.status_code == 404
    assert executed == ["filesystem__write_file"]


def test_approve_by_other_user_is_not_found(approve_app):
    app, store, executed, current = approve_app
    store.save(pending_checkpoint("run-1", "alice"))
    current["user_id"] = "mallory"
    c = TestClient(app)

    r = c.post("/approve", json={"approval_id": "run-1", "decision": "approve"})
    # 404, not 403: a foreign run id must not confirm that the run exists.
    assert r.status_code == 404
    assert executed == []
    assert store.rows["run-1"].pending_tool is not None  # untouched


def test_approve_rejects_bad_decision(approve_app):
    app, store, _, _ = approve_app
    store.save(pending_checkpoint("run-1", "alice"))
    r = TestClient(app).post("/approve", json={"approval_id": "run-1", "decision": "maybe"})
    assert r.status_code == 422


# -------------------------------------------------------- concurrency

def test_in_flight_cap_per_user():
    async def scenario():
        gates = [asyncio.Event() for _ in range(concurrency.MAX_IN_FLIGHT_PER_USER)]

        async def hold(ev):
            async with concurrency.run_slot("bob"):
                await ev.wait()

        tasks = [asyncio.create_task(hold(ev)) for ev in gates]
        await asyncio.sleep(0)  # let them all acquire
        assert concurrency.in_flight("bob") == concurrency.MAX_IN_FLIGHT_PER_USER

        with pytest.raises(HTTPException) as ei:
            async with concurrency.run_slot("bob"):
                pass
        assert ei.value.status_code == 429
        assert ei.value.headers["Retry-After"]

        # Another user is unaffected.
        async with concurrency.run_slot("carol"):
            assert concurrency.in_flight("carol") == 1

        for ev in gates:
            ev.set()
        await asyncio.gather(*tasks)
        assert concurrency.in_flight("bob") == 0

    asyncio.run(scenario())


# ------------------------------------------------------- request model

def test_ask_request_bounds():
    AskRequest(question="hi", history=[{"role": "user", "content": "a"},
                                        {"role": "assistant", "content": "b"}])
    with pytest.raises(ValueError):
        AskRequest(question="x" * 9000)
    with pytest.raises(ValueError):
        AskRequest(question="hi", history=[{"role": "system", "content": "override"}])
    with pytest.raises(ValueError):
        AskRequest(question="hi", history=[{"role": "user", "content": "a"}] * 21)
    with pytest.raises(ValueError):
        AskRequest(question="hi", history=[{"role": "user", "content": "x" * 5000}])


def test_history_reaches_the_model_and_owner_is_stamped():
    store, provider = FakeStore(), EchoProvider()

    async def go():
        r = await run_agent(
            question="and the second one?",
            prompt_text="SYS",
            registry=ToolRegistry(),
            provider=provider,
            policy=ToolPolicy(tiers={}),
            audit=AuditLog(),
            store=store,
            thread_id="t-1",
            trace=Trace(trace_id="t-1"),
            user_id="alice",
            history=[{"role": "user", "content": "first?"},
                     {"role": "assistant", "content": "first answer"}],
        )
        # checkpoint writes are fire-and-forget; let them land
        await asyncio.gather(*list(loop_module._pending_saves))
        return r

    result = asyncio.run(go())
    assert result.answer == "ok"
    roles = [m["role"] for m in provider.seen[0]]
    assert roles == ["system", "user", "assistant", "user"]
    assert provider.seen[0][-1]["content"] == "and the second one?"
    assert store.rows["t-1"].user_id == "alice"


# ----------------------------------------------------------- cache key

def test_cache_key_covers_history_and_mode():
    base = dict(question="q", prompt_version="p", model="m", tool_names=["a"], session_id="u")
    k0 = answer_key(**base)
    assert answer_key(**base) == k0
    assert answer_key(**base, history=[{"role": "user", "content": "earlier"}]) != k0
    assert answer_key(**base, docs_only=True) != k0
    assert answer_key(**{**base, "session_id": "other"}) != k0
