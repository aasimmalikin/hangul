"""Run an eval suite against the real agent and save a versioned report.

    python run_evals.py                      # qa (correctness + faithfulness), as before
    python run_evals.py --suite tool_selection
    python run_evals.py --suite all --limit 3

Both suites call the real model and (for judged metrics) the real judge, so
they cost money. Reports land in data/eval_runs/<suite>-<UTC stamp>.json and
show up on the admin page."""

import argparse
import asyncio

from harness.eval.agent_runner import run_suite
from harness.eval.catalog import SUITES


def _print(report: dict) -> None:
    print(f"suite:   {report['suite']}   cases: {report['n']}   prompt={report.get('prompt_version')}  "
          f"model={report.get('model')}")
    for k, v in report["metrics"].items():
        print(f"  {k:<28} {v}")
    print("per-case:")
    for c in report["cases"]:
        s = c["scores"]
        summary = "  ".join(f"{k}={v:.2f}" for k, v in s.items() if isinstance(v, (int, float)))
        print(f"  {c['id']}: {summary}")
        for note in s.get("notes", []) or []:
            print(f"      - {note}")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--suite", default="qa", choices=[*SUITES, "all"])
    ap.add_argument("--limit", type=int, default=None, help="only the first N cases")
    ap.add_argument("--ids", default=None, help="comma-separated case ids to run, e.g. ts15,ts16")
    ap.add_argument("--no-save", action="store_true")
    args = ap.parse_args()

    suites = list(SUITES) if args.suite == "all" else [args.suite]
    for suite in suites:
        print(f"\nrunning {suite} ...\n")
        report, path = await run_suite(suite, save=not args.no_save, limit=args.limit,
                                       ids=args.ids.split(",") if args.ids else None)
        _print(report)
        if path:
            print(f"\nsaved report -> {path}")


if __name__ == "__main__":
    asyncio.run(main())
