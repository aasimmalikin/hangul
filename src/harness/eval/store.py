"""Eval reports on disk, plus the state of a run started from the admin page.

Reports are ``data/eval_runs/<suite>-<UTC stamp>.json``; the original QA
runs are ``eval-<stamp>.json`` and are treated as suite ``qa``."""

import asyncio
import json
import re
import time
from datetime import UTC, datetime
from pathlib import Path

EVAL_DIR = Path("data/eval_runs")
_NAME = re.compile(r"^(?P<suite>[a-z_]+)-(?P<stamp>\d{8}-\d{6})\.json$")


def _suite_of(name: str) -> str | None:
    m = _NAME.match(name)
    if not m:
        return None
    s = m.group("suite")
    return "qa" if s == "eval" else s


def list_reports(suite: str | None = None, limit: int = 50) -> list[dict]:
    if not EVAL_DIR.exists():
        return []
    out = []
    for p in sorted(EVAL_DIR.glob("*.json"), reverse=True):
        s = _suite_of(p.name)
        if s is None or (suite and s != suite):
            continue
        try:
            r = json.loads(p.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        out.append({"file": p.name, "suite": s, "created": _NAME.match(p.name).group("stamp"),
                    "n": r.get("n"), "metrics": r.get("metrics") or _legacy_metrics(r),
                    "prompt_version": r.get("prompt_version"), "model": r.get("model")})
        if len(out) >= limit:
            break
    return out


def _legacy_metrics(r: dict) -> dict:
    return {k: r[k] for k in ("avg_correctness", "avg_faithfulness", "pass_rate") if k in r}


def load_report(file: str) -> dict | None:
    if _suite_of(file) is None:      # also rejects any path tricks
        return None
    p = EVAL_DIR / file
    if not p.exists():
        return None
    r = json.loads(p.read_text())
    r.setdefault("suite", _suite_of(file))
    r.setdefault("metrics", _legacy_metrics(r))
    return r


def latest(suite: str) -> dict | None:
    rows = list_reports(suite, limit=1)
    return load_report(rows[0]["file"]) if rows else None


def save_report(suite: str, report: dict) -> Path:
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    prefix = "eval" if suite == "qa" else suite
    p = EVAL_DIR / f"{prefix}-{stamp}.json"
    p.write_text(json.dumps(report, indent=2, default=str))
    return p


# ------------------------------------------------------- runs in progress

class RunState:
    """One in-process record per suite of the last run started from the API."""

    def __init__(self) -> None:
        self._runs: dict[str, dict] = {}
        self._tasks: dict[str, asyncio.Task] = {}

    def status(self) -> dict[str, dict]:
        return {k: dict(v) for k, v in self._runs.items()}

    def is_running(self, suite: str) -> bool:
        t = self._tasks.get(suite)
        return t is not None and not t.done()

    def start(self, suite: str, coro, *, started_by: str) -> dict:
        if self.is_running(suite):
            raise RuntimeError(f"suite {suite!r} is already running")
        rec = {"suite": suite, "state": "running", "started_at": time.time(), "started_by": started_by,
               "finished_at": None, "file": None, "error": None}
        self._runs[suite] = rec

        async def wrapped():
            try:
                path = await coro
                rec["file"] = Path(path).name if path else None
                rec["state"] = "done"
            except Exception as e:  # noqa: BLE001 - surfaced to the admin page
                rec["state"] = "failed"
                rec["error"] = f"{type(e).__name__}: {e}"
            finally:
                rec["finished_at"] = time.time()

        self._tasks[suite] = asyncio.create_task(wrapped())
        return dict(rec)


run_state = RunState()
