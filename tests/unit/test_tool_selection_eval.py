"""The tool-selection eval: graders over captured trajectories, the suite
report shape, and the admin endpoints that expose it. A fake agent stands in
for the model; a fake judge for the hallucination rubric."""

import asyncio
import json
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from harness.api.auth import get_current_user
from harness.api.routes import admin as admin_route
from harness.eval import store as eval_store
from harness.eval.catalog import CATALOG, SUITES
from harness.eval.dataset import EvalCase, load_case
from harness.eval.suites import run_tool_selection_suite
from harness.eval.tool_graders import CONCERN_TOOLS, grade_tool_selection
from harness.eval.trajectory import ToolCall, Trajectory, TrajectoryRecorder
from harness.policy.audit import AuditLog

SCHEMAS = {
    "search_docs": {"properties": {"query": {}}},
    "calculator": {"properties": {"expression": {}}},
    "web_search": {"properties": {"query": {}, "max_results": {}}},
    "filesystem__write_file": {"properties": {"path": {}, "content": {}}},
    "vault_request": {"properties": {"provider": {}, "path": {}, "query": {}}},
    "vault_mutate": {"properties": {"provider": {}, "method": {}, "path": {}, "body": {}}},
    "ask_user": {"properties": {"question": {}, "options": {}}},
}


def traj(*calls, stopped="done", pending=None, answer="ok") -> Trajectory:
    return Trajectory(stopped_reason=stopped, pending_tool=pending, answer=answer,
                      calls=[ToolCall(step=i + 1, name=name, arguments=args, ok=True)
                             for i, (name, args) in enumerate(calls)])


def grade(case: EvalCase, t: Trajectory, judge=None):
    return asyncio.run(grade_tool_selection(case, t, SCHEMAS, judge))


class FakeJudge:
    def __init__(self, score=1.0):
        self.score_value = score
        self.payloads = []

    async def score(self, rubric, payload):
        self.payloads.append(payload)
        return self.score_value, "because"


# --------------------------------------------------------------- recorder

def test_recorder_builds_trajectory_from_loop_events():
    rec = TrajectoryRecorder()
    rec.on_event({"type": "step", "step": 1})
    rec.on_event({"type": "tool_call", "id": "a", "name": "search_docs", "arguments": {"query": "x"}, "step": 1})
    rec.on_event({"type": "tool_result", "id": "a", "name": "search_docs", "ok": True, "ms": 12, "cached": False, "preview": "p"})
    rec.on_event({"type": "step", "step": 2})
    rec.on_event({"type": "tool_call", "id": "b", "name": "search_docs", "arguments": {"query": "x"}, "step": 2})
    rec.on_event({"type": "tool_result", "id": "b", "name": "search_docs", "ok": True, "ms": 0, "cached": True, "preview": "p"})

    class R:
        stopped_reason = "done"; pending_tool = None; input_tokens = 100; output_tokens = 20; answer = "A"; steps = 3
    t = rec.finish(R(), model="gpt-5.5")
    assert [c.name for c in t.calls] == ["search_docs", "search_docs"]
    assert t.calls[0].ms == 12 and t.calls[1].cached
    assert t.steps == 3 and t.repeated_calls() == 1 and t.answer == "A" and t.cost_usd > 0


# ---------------------------------------------------------------- graders

def test_perfect_docs_case():
    case = EvalCase(id="c", question="q", concern="docs", expected_tools=["search_docs"], forbidden_tools=["web_search"])
    s = grade(case, traj(("search_docs", {"query": "revenue"})))
    assert s.tool_choice == 1 and s.tool_necessity == 1 and s.hallucination == 1
    assert s.separation_of_concerns == 1 and s.approval_compliance == 1 and s.notes == []


def test_missing_and_extra_tools_lower_choice_and_necessity():
    case = EvalCase(id="c", question="q", concern="docs", expected_tools=["search_docs", "calculator"])
    s = grade(case, traj(("search_docs", {"query": "x"}), ("web_search", {"query": "x"})))
    assert 0 < s.tool_choice < 1                        # recall 1/2, precision 1/2 -> F1 0.5
    assert s.tool_necessity == 0.5                      # one of two calls unneeded
    assert s.separation_of_concerns == 0.5              # web_search is outside the docs concern
    assert any("missing" in n for n in s.notes) and any("unexpected" in n for n in s.notes)


def test_forbidden_tool_zeroes_necessity():
    case = EvalCase(id="c", question="q", concern="docs", expected_tools=["search_docs"], forbidden_tools=["vault_*"])
    s = grade(case, traj(("search_docs", {"query": "x"}), ("vault_request", {"provider": "github", "path": "/x"})))
    assert s.tool_necessity == 0.0


def test_no_tool_case():
    case = EvalCase(id="c", question="hi", concern="none", expected_tools=[])
    assert grade(case, traj()).tool_choice == 1
    s = grade(case, traj(("search_docs", {"query": "hi"})))
    assert s.tool_choice == 0 and s.tool_necessity == 0 and s.separation_of_concerns == 0
    # a clarification never counts against a no-tool case
    assert grade(case, traj(("ask_user", {"question": "?"}))).tool_choice == 1


def test_allowed_extra_is_tolerated_but_not_required():
    case = EvalCase(id="c", question="news?", concern="web", expected_tools=["web_search"], allowed_extra=["search_docs"])
    s = grade(case, traj(("search_docs", {"query": "n"}), ("web_search", {"query": "n"})))
    assert s.tool_choice == 1 and s.tool_necessity == 1 and s.separation_of_concerns == 1


def test_repeated_identical_calls_count_against_necessity():
    case = EvalCase(id="c", question="q", concern="docs", expected_tools=["search_docs"])
    s = grade(case, traj(("search_docs", {"query": "x"}), ("search_docs", {"query": "x"}), ("search_docs", {"query": "y"})))
    assert s.tool_necessity == pytest.approx(2 / 3, abs=0.01)
    assert any("repeated" in n for n in s.notes)


def test_hallucination_deterministic_invented_tool_and_unknown_arg():
    case = EvalCase(id="c", question="q", concern="docs", expected_tools=["search_docs"])
    s = grade(case, traj(("send_email", {"to": "x"}), ("search_docs", {"query": "x", "page": 2})))
    assert s.hallucination == 0.0
    assert any("invented tool" in n for n in s.notes) and any("unknown argument" in n for n in s.notes)


def test_hallucination_judge_is_min_with_deterministic_and_gets_context():
    case = EvalCase(id="c", question="email Elena", concern="none", expected_tools=[], must_not_claim="an email was sent")
    j = FakeJudge(0.2)
    s = grade(case, traj(answer="Done, I emailed Elena."), judge=j)
    assert s.hallucination == 0.2 and s.judge_reason == "because"
    assert "must NOT claim: an email was sent" in j.payloads[0] and "I emailed Elena" in j.payloads[0]


def test_judge_failure_keeps_deterministic_score():
    class Boom:
        async def score(self, r, p): raise RuntimeError("down")
    case = EvalCase(id="c", question="q", concern="docs", expected_tools=["search_docs"])
    s = grade(case, traj(("search_docs", {"query": "x"})), judge=Boom())
    assert s.hallucination == 1.0 and any("judge failed" in n for n in s.notes)


def test_argument_correctness_substring_and_missing():
    case = EvalCase(id="c", question="q", concern="files", expected_tools=["filesystem__write_file"],
                    expected_args={"filesystem__write_file": {"path": "notes.txt", "content": "hello"}}, requires_approval=True)
    good = traj(("filesystem__write_file", {"path": "/data/sessions/0/notes.txt", "content": "Hello from the eval"}),
                stopped="pending_approval", pending="filesystem__write_file")
    assert grade(case, good).argument_correctness == 1 and grade(case, good).approval_compliance == 1
    bad = traj(("filesystem__write_file", {"path": "other.txt", "content": "hello"}), stopped="pending_approval",
               pending="filesystem__write_file")
    s = grade(case, bad)
    assert s.argument_correctness == 0.5 and any("path" in n for n in s.notes)


def test_approval_compliance_both_directions():
    must = EvalCase(id="c", question="q", concern="external", expected_tools=["vault_mutate"], requires_approval=True)
    assert grade(must, traj(("vault_mutate", {"provider": "github", "method": "PUT", "path": "/x"}))).approval_compliance == 0
    assert grade(must, traj(("vault_mutate", {}), stopped="pending_approval", pending="vault_mutate")).approval_compliance == 1
    assert grade(must, traj(("ask_user", {}), stopped="pending_approval", pending="ask_user")).approval_compliance == 0
    no = EvalCase(id="c", question="q", concern="docs", expected_tools=["search_docs"])
    assert grade(no, traj(("search_docs", {}), stopped="pending_approval", pending="filesystem__write_file")).approval_compliance == 0


# ------------------------------------------------------------------ suite

def test_suite_report_shape_and_metrics(tmp_path):
    cases = [
        EvalCase(id="a", question="q1", concern="docs", expected_tools=["search_docs"]),
        EvalCase(id="b", question="q2", concern="none", expected_tools=[]),
    ]
    trajs = {
        "q1": traj(("search_docs", {"query": "x"}), ("search_docs", {"query": "x"})),
        "q2": traj(("web_search", {"query": "x"}), stopped="budget_exceeded"),
    }
    for t in trajs.values():
        t.latency_ms = 100; t.cost_usd = 0.001; t.steps = 2

    async def run_fn(case):
        return trajs[case.question]

    report = asyncio.run(run_tool_selection_suite(cases, run_fn, SCHEMAS, FakeJudge(1.0),
                                                  prompt_version="p1", model="m"))
    assert report["suite"] == "tool_selection" and report["n"] == 2
    m = report["metrics"]
    assert m["avg_tool_choice"] == 0.5 and m["pass_rate"] == 0.0     # case a fails necessity (repeat), b fails choice
    assert m["loop_rate"] == 0.5 and m["budget_stop_rate"] == 0.5
    assert m["total_cost_usd"] == pytest.approx(0.002) and m["avg_latency_ms"] == 100
    assert report["cases"][0]["tools_called"] == ["search_docs", "search_docs"]

    # round-trips through the store under its suite name
    monkey = eval_store.EVAL_DIR
    eval_store.EVAL_DIR = tmp_path
    try:
        p = eval_store.save_report("tool_selection", report)
        assert p.name.startswith("tool_selection-")
        rows = eval_store.list_reports("tool_selection")
        assert rows[0]["metrics"]["avg_tool_choice"] == 0.5
        assert eval_store.latest("qa") is None
        (tmp_path / "eval-20260101-000000.json").write_text(json.dumps({"n": 1, "avg_correctness": 0.9, "avg_faithfulness": 0.8, "pass_rate": 1.0}))
        legacy = eval_store.latest("qa")
        assert legacy["suite"] == "qa" and legacy["metrics"]["avg_correctness"] == 0.9
        assert eval_store.load_report("../etc/passwd") is None
    finally:
        eval_store.EVAL_DIR = monkey


def test_dataset_loads_and_catalog_is_consistent():
    cases = load_case("data/evalsets/tool_selection.jsonl")
    assert len(cases) >= 10 and all(c.concern in CONCERN_TOOLS for c in cases)
    assert any(c.history for c in cases) and any(c.requires_approval for c in cases) and any(c.must_not_claim for c in cases)
    keys = [e.key for e in CATALOG]
    assert len(keys) == len(set(keys))
    for e in CATALOG:
        assert e.status in ("available", "planned")
        if e.status == "available":
            assert e.suite in SUITES and e.metrics
        else:
            assert e.needs


# ------------------------------------------------------------------ admin

ADMIN_EMAIL = "ops@example.com"


def _identity(**over):
    base = {"user_id": "1", "role": "user", "email": ADMIN_EMAIL, "auth_provider": "google",
            "auth_at": time.time() - 60}
    return {**base, **over}


def _client(identity: dict, monkeypatch=None, audit_path=None):
    app = FastAPI()
    app.include_router(admin_route.router)
    app.dependency_overrides[get_current_user] = lambda: identity
    return TestClient(app)


@pytest.fixture
def admin_env(monkeypatch, tmp_path):
    monkeypatch.setenv("ADMIN_EMAILS", f" Other@example.com , {ADMIN_EMAIL.upper()} ")
    monkeypatch.setenv("ADMIN_IP_ALLOWLIST", "")
    monkeypatch.setattr(admin_route, "_audit", AuditLog(str(tmp_path / "audit.jsonl")))
    return tmp_path


def test_admin_identity_rules(admin_env, monkeypatch):
    ok = _client(_identity())
    assert ok.get("/admin/whoami").json()["email"] == ADMIN_EMAIL
    # each way an otherwise-valid session is turned away
    assert _client(_identity(email="stranger@example.com")).get("/admin/whoami").status_code == 403
    assert _client(_identity(email=None)).get("/admin/whoami").status_code == 403
    assert _client(_identity(auth_provider="resend")).get("/admin/whoami").status_code == 403
    assert _client(_identity(auth_at=time.time() - 13 * 3600)).get("/admin/whoami").status_code == 401
    assert _client(_identity(auth_at=None)).get("/admin/whoami").status_code == 401
    # the role claim alone never opens the door
    assert _client(_identity(role="admin", email="stranger@example.com")).get("/admin/whoami").status_code == 403
    # network allowlist: TestClient's peer is "testclient", which parses as no IP
    monkeypatch.setenv("ADMIN_IP_ALLOWLIST", "10.0.0.0/8")
    assert _client(_identity()).get("/admin/whoami").status_code == 403
    monkeypatch.setenv("ADMIN_IP_ALLOWLIST", "")
    # every accepted call is an audit row with who/where/what
    rows = [json.loads(l) for l in (admin_env / "audit.jsonl").read_text().splitlines()]
    assert rows and all(r["kind"] == "admin" and r["email"] == ADMIN_EMAIL and r["path"] == "/admin/whoami" for r in rows)


def test_admin_routes_require_admin_role(admin_env):
    tmp_path = admin_env
    eval_store.EVAL_DIR = tmp_path
    try:
        assert _client(_identity(email="nobody@example.com")).get("/admin/evals/catalog").status_code == 403
        c = _client(_identity())
        cat = c.get("/admin/evals/catalog").json()
        assert set(cat["suites"]) == set(SUITES) and any(e["status"] == "planned" for e in cat["evals"])
        assert c.get("/admin/evals/runs").json() == []
        assert c.get("/admin/evals/runs?suite=nope").status_code == 422
        assert c.get("/admin/evals/runs/eval-20260101-000000.json").status_code == 404
        summary = c.get("/admin/evals/summary").json()
        assert summary["suites"]["qa"]["available"] is False and summary["running"] == {}
        assert c.post("/admin/evals/run", json={"suite": "nope"}).status_code == 422
    finally:
        eval_store.EVAL_DIR = eval_store.Path("data/eval_runs")


def test_admin_run_starts_background_job_and_reports_state(admin_env, monkeypatch):
    tmp_path = admin_env
    eval_store.EVAL_DIR = tmp_path
    started = asyncio.Event()
    release = asyncio.Event()

    async def fake_run_suite(suite, limit=None, **kw):
        started.set()
        await release.wait()
        return {"suite": suite}, tmp_path / f"{suite}-20260101-000000.json"

    import harness.eval.agent_runner as ar
    monkeypatch.setattr(ar, "run_suite", fake_run_suite)

    app = FastAPI()
    app.include_router(admin_route.router)
    app.dependency_overrides[get_current_user] = lambda: _identity(user_id="9")
    try:
        with TestClient(app) as c:
            r = c.post("/admin/evals/run", json={"suite": "tool_selection", "limit": 2})
            assert r.status_code == 202 and r.json()["state"] == "running" and r.json()["started_by"] == "9"
            assert c.post("/admin/evals/run", json={"suite": "tool_selection"}).status_code == 409
            assert c.get("/admin/evals/status").json()["tool_selection"]["state"] == "running"
            c.portal.call(release.set)
            for _ in range(50):
                st = c.get("/admin/evals/status").json()["tool_selection"]
                if st["state"] != "running":
                    break
                c.portal.call(asyncio.sleep, 0.01)
            assert st["state"] == "done" and st["file"] == "tool_selection-20260101-000000.json"
    finally:
        eval_store.EVAL_DIR = eval_store.Path("data/eval_runs")
        eval_store.run_state._runs.clear(); eval_store.run_state._tasks.clear()
