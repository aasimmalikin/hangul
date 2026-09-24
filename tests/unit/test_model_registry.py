"""The model registry: what a user may pick, what it costs, how effort maps
to the API parameter and the loop budget -- and that /ask and /models honour it.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from harness.agent.loop import AgentResult
from harness.api.auth import get_current_user
from harness.api.routes import ask as ask_route
from harness.api.routes import models as models_route
from harness.obs.tracing import cost_usd
from harness.providers import registry
from harness.providers.openai_provider import OpenAIProvider

# ------------------------------------------------------------- registry

def test_default_model_is_registered():
    spec, effort = registry.resolve(None, None)
    assert spec.id == registry.default_model_id()
    assert effort in spec.efforts


def test_every_reasoning_model_has_a_valid_default_effort():
    for spec in registry.list_models():
        if spec.supports_reasoning:
            assert spec.efforts and spec.default_effort in spec.efforts
            assert all(e in registry.EFFORT_BUDGETS for e in spec.efforts)
        else:
            assert spec.efforts == () and spec.default_effort is None


def test_resolve_rejects_unknown_model_and_bad_effort():
    with pytest.raises(ValueError):
        registry.resolve("gpt-does-not-exist", None)
    with pytest.raises(ValueError):
        registry.resolve("gpt-5.5", "turbo")
    # a non-reasoning model takes no effort at all
    with pytest.raises(ValueError):
        registry.resolve("gpt-4.1", "high")
    assert registry.resolve("gpt-4.1", None) == (registry.get_model("gpt-4.1"), None)


def test_budget_scales_with_effort():
    assert registry.budget_for(None) == registry.DEFAULT_BUDGET
    assert registry.budget_for("low").max_steps < registry.budget_for("medium").max_steps
    assert registry.budget_for("medium").max_tokens < registry.budget_for("high").max_tokens


def test_cost_comes_from_registry():
    spec = registry.get_model("gpt-5.5")
    assert cost_usd("gpt-5.5", 1_000_000, 1_000_000) == pytest.approx(
        spec.input_usd_per_m + spec.output_usd_per_m)
    assert cost_usd("gpt-unknown", 1_000_000, 0) == 0.0


# ------------------------------------------------------------- provider

def test_bound_provider_shares_client_and_sends_effort():
    base = OpenAIProvider(api_key="k", model="gpt-5.5")
    p = base.bound("gpt-5.4-mini", "low")
    assert p.client is base.client
    kwargs = p._base_kwargs([{"role": "user", "content": "hi"}], [], None)
    assert kwargs["model"] == "gpt-5.4-mini"
    assert kwargs["reasoning_effort"] == "low"
    # non-reasoning: the parameter must be absent, not None
    assert "reasoning_effort" not in base.bound("gpt-4.1", None)._base_kwargs([], [], None)


# ------------------------------------------------------------- routes

@pytest.fixture
def ask_app(monkeypatch):
    runs: list[dict] = []

    async def fake_run_agent(**kw):
        runs.append(kw)
        return AgentResult(answer="done", steps=1, stopped_reason="answered",
                           input_tokens=1, output_tokens=1)

    class FakeCache:
        async def get(self, key): return None
        async def set(self, key, value): pass

    class FakeProvider:
        def __init__(self, model, effort):
            self.model, self.reasoning_effort = model, effort

    class FakePrompt:
        text = "sys"
        version = "v1"

    monkeypatch.setattr(ask_route, "run_agent", fake_run_agent)
    monkeypatch.setattr(ask_route, "_cache", FakeCache())
    monkeypatch.setattr(ask_route, "provider_for", lambda spec, effort: FakeProvider(spec.id, effort))
    monkeypatch.setattr(ask_route, "get_prompt", lambda name: FakePrompt())
    monkeypatch.setattr(ask_route, "profile_text", lambda uid: "")
    monkeypatch.setattr(ask_route, "_spawn_bookkeeping", lambda coro: coro.close())
    monkeypatch.setattr(ask_route, "_trace_store", type("T", (), {"add": lambda *a: None})())

    app = FastAPI()
    app.include_router(ask_route.router)
    app.include_router(models_route.router)
    app.dependency_overrides[get_current_user] = lambda: {"user_id": "alice", "role": "user"}
    return TestClient(app), runs


def test_ask_rejects_unknown_model(ask_app):
    client, runs = ask_app
    r = client.post("/ask", json={"question": "hi", "model": "gpt-nope"})
    assert r.status_code == 422
    assert "gpt-nope" in r.json()["detail"]
    r = client.post("/ask", json={"question": "hi", "model": "gpt-4.1", "effort": "high"})
    assert r.status_code == 422
    assert runs == []


def test_ask_binds_selected_model_effort_and_budget(ask_app):
    client, runs = ask_app
    r = client.post("/ask", json={"question": "hi", "model": "gpt-5.4-mini", "effort": "high"})
    assert r.status_code == 200, r.text
    assert r.json()["model"] == "gpt-5.4-mini"
    assert r.json()["effort"] == "high"
    kw = runs[0]
    assert (kw["provider"].model, kw["provider"].reasoning_effort) == ("gpt-5.4-mini", "high")
    high = registry.budget_for("high")
    assert (kw["max_steps"], kw["max_tokens"]) == (high.max_steps, high.max_tokens)


def test_ask_without_selection_uses_default(ask_app):
    client, runs = ask_app
    r = client.post("/ask", json={"question": "hi"})
    assert r.status_code == 200, r.text
    spec, effort = registry.resolve(None, None)
    assert r.json()["model"] == spec.id
    assert runs[0]["provider"].reasoning_effort == effort


def test_models_endpoint_lists_registry(ask_app):
    client, _ = ask_app
    r = client.get("/models")
    assert r.status_code == 200
    body = r.json()
    assert body["default"]["model"] == registry.default_model_id()
    ids = [m["id"] for m in body["models"]]
    assert ids == [s.id for s in registry.list_models()]
    m = body["models"][0]
    assert {"id", "label", "input_usd_per_m", "output_usd_per_m",
            "supports_reasoning", "efforts", "default_effort"} <= set(m)
