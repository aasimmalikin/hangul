"""CI eval gate: run a suite against the real agent and fail if it's below its
floors or has regressed against its saved baseline (harness.eval.gate).

    python ci_gate.py                       # the shop copilot (business) -- the product's gate
    python ci_gate.py --suite qa            # answers from the owner's documents
    python ci_gate.py --suite all           # business, qa and tool_selection
    python ci_gate.py --update-baseline     # save this run as the baseline (after a deliberate change)

Calls the real model and judge, so it costs money. Baselines live in
data/eval_baseline.json (qa) and data/eval_baseline_<suite>.json.
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

from harness.eval.agent_runner import run_suite
from harness.eval.gate import FLOORS, evaluate_gate

GATED = ("business", "qa", "tool_selection")


def baseline_path(suite: str) -> Path:
    return Path("data/eval_baseline.json") if suite == "qa" else Path(f"data/eval_baseline_{suite}.json")


def gate_one(suite: str, update: bool) -> bool:
    report, saved = asyncio.run(run_suite(suite))
    path = baseline_path(suite)
    baseline = json.loads(path.read_text()) if path.exists() and not update else None
    result = evaluate_gate(report, baseline, suite=suite)
    m = report.get("metrics") or report
    print("=" * 60)
    print(f"{suite.upper()} GATE - {'PASS' if result.passed else 'FAIL'}   (report: {saved})")
    print("  " + "  ".join(f"{k}={m.get(k, 0):.2f}" for k in FLOORS[suite]))
    for note in result.advisory_notes:
        print(f"  [note] {note}")
    for fail in result.blocking_failures:
        print(f"  [BLOCKING] {fail}")
    if update:
        keep = {k: m.get(k) for k in m if isinstance(m.get(k), (int, float))}
        path.write_text(json.dumps({**keep, "prompt_version": report.get("prompt_version"),
                                    "model": report.get("model"), "n": report.get("n")}, indent=2) + "\n")
        print(f"  baseline saved -> {path}")
    return result.passed


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--suite", default="business", choices=[*GATED, "all"])
    ap.add_argument("--update-baseline", action="store_true")
    args = ap.parse_args()
    suites = GATED if args.suite == "all" else (args.suite,)
    ok = [gate_one(s, args.update_baseline) for s in suites]
    return 0 if all(ok) else 1


if __name__ == "__main__":
    sys.exit(main())
