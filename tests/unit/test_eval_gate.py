"""The CI gate: per-suite floors, regressions against a baseline, both report shapes."""
from harness.eval.gate import FLOORS, evaluate_gate


def test_the_business_gate_uses_its_own_floors():
    good = {"metrics": {"pass_rate": 0.94, "avg_hallucination": 1.0, "avg_argument_correctness": 1.0,
                        "avg_approval_compliance": 1.0}}
    assert evaluate_gate(good, suite="business").passed
    bad = {"metrics": {**good["metrics"], "avg_hallucination": 0.8}}
    r = evaluate_gate(bad, suite="business")
    assert not r.passed and r.blocking_failures == ["avg_hallucination = 0.80 below floor 0.90"]


def test_a_regression_is_reported_once_and_a_dip_only_noted():
    base = {"metrics": {"pass_rate": 1.0, "avg_hallucination": 1.0, "avg_argument_correctness": 1.0,
                        "avg_approval_compliance": 1.0}}
    now = {"metrics": {**base["metrics"], "pass_rate": 0.89, "avg_argument_correctness": 0.97}}
    r = evaluate_gate(now, base, suite="business")
    assert r.blocking_failures == ["pass_rate regressed 1.00 -> 0.89 (drop 0.11 > noise 0.05)"]
    assert r.advisory_notes == ["avg_argument_correctness dipped 1.00 -> 0.97 (within noise, not blocking)"]


def test_old_qa_reports_with_top_level_metrics_still_gate():
    report = {"avg_correctness": 0.9, "avg_faithfulness": 0.95, "pass_rate": 0.9}
    assert evaluate_gate(report).passed
    assert not evaluate_gate({**report, "avg_correctness": 0.5}).passed
    assert set(FLOORS) >= {"business", "qa", "tool_selection"}
