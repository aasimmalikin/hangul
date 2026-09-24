"""Admin-only endpoints behind the admin page: the eval catalog, stored
reports, and starting a suite run.

Every route requires the ``admin`` role on the service JWT (``require_admin``),
which means an allowlisted Google email with a recent sign-in (see auth.require_admin)."""

import asyncio
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from harness.api.auth import admin_emails, require_admin
from harness.api.routes.ask import _audit, _trace_store
from harness.config import get_settings
from harness.eval import store as eval_store
from harness.eval.catalog import SUITES, catalog
from harness.eval.gate import evaluate_gate


async def _audited_admin(request: Request, user: dict = Depends(require_admin)) -> dict:
    """Every admin call is an audit row -- who, from where, what."""
    _audit.record_admin(email=user.get("email"), user_id=user["user_id"], ip=user.get("ip"),
                        method=request.method, path=request.url.path)
    return user


router = APIRouter(prefix="/admin", dependencies=[Depends(_audited_admin)])

_BASELINE = Path("data/eval_baseline.json")


class RunRequest(BaseModel):
    suite: str = Field(min_length=1, max_length=32)
    limit: int | None = Field(default=None, ge=1, le=500)


@router.get("/whoami")
async def whoami(user: dict = Depends(require_admin)) -> dict:
    """The page's first call after Google sign-in: 200 means this account is
    on the allowlist; 401/403 (from the dependency) says why not."""
    return {"authorized": True, "email": user["email"], "auth_provider": user["auth_provider"],
            "auth_at": user["auth_at"], "max_auth_age_s": get_settings().admin_max_auth_age_s,
            "allowlist_size": len(admin_emails())}


@router.get("/evals/catalog")
async def evals_catalog() -> dict:
    return {"suites": SUITES, "evals": catalog()}


@router.get("/evals/runs")
async def evals_runs(suite: str | None = None, limit: int = 20) -> list[dict]:
    if suite is not None and suite not in SUITES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"unknown suite {suite!r}")
    return await asyncio.to_thread(eval_store.list_reports, suite, max(1, min(limit, 100)))


@router.get("/evals/runs/{file}")
async def evals_run(file: str) -> dict:
    report = await asyncio.to_thread(eval_store.load_report, file)
    if report is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "report not found")
    return report


@router.get("/evals/summary")
async def evals_summary() -> dict:
    """Latest report per suite plus the CI-gate verdict for qa -- the numbers
    the admin page shows at the top."""
    out: dict = {"suites": {}, "running": eval_store.run_state.status()}
    for suite in SUITES:
        latest = await asyncio.to_thread(eval_store.latest, suite)
        entry: dict = {"available": latest is not None}
        if latest is not None:
            entry.update({"n": latest.get("n"), "metrics": latest.get("metrics"),
                          "prompt_version": latest.get("prompt_version"), "model": latest.get("model")})
            if suite == "qa":
                import json
                baseline = json.loads(_BASELINE.read_text()) if _BASELINE.exists() else None
                gate = evaluate_gate(latest, baseline)
                entry["gate"] = {"passed": gate.passed, "blocking_failures": gate.blocking_failures,
                                 "advisory_notes": gate.advisory_notes}
        out["suites"][suite] = entry
    return out


@router.post("/evals/run", status_code=status.HTTP_202_ACCEPTED)
async def evals_run_start(req: RunRequest, user: dict = Depends(require_admin)) -> dict:
    """Start a suite in the background. Costs real model + judge calls."""
    if req.suite not in SUITES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"unknown suite {req.suite!r}")
    if eval_store.run_state.is_running(req.suite):
        raise HTTPException(status.HTTP_409_CONFLICT, f"{req.suite} is already running")
    from harness.eval.agent_runner import run_suite

    async def job():
        _, path = await run_suite(req.suite, limit=req.limit)
        return path

    return eval_store.run_state.start(req.suite, job(), started_by=user["user_id"])


@router.get("/evals/status")
async def evals_status() -> dict:
    return eval_store.run_state.status()


@router.get("/security")
async def security_overview(limit: int = 50) -> dict:
    """Prompt-injection events from the audit log: counts by layer / severity
    / action, plus the newest rows (no message bodies, only reasons)."""
    from collections import Counter
    rows = await asyncio.to_thread(_audit.entries, "security", 2000)
    by_layer = Counter(r.get("layer") for r in rows)
    by_severity = Counter(r.get("severity") for r in rows)
    by_action = Counter(r.get("action") for r in rows)
    by_source = Counter(r.get("source") for r in rows if r.get("layer") in ("tool_result", "upload"))
    return {
        "total": len(rows),
        "by_layer": dict(by_layer), "by_severity": dict(by_severity), "by_action": dict(by_action),
        "top_sources": by_source.most_common(8),
        "recent": rows[:max(1, min(limit, 200))],
        "config": {"llm_screen": get_settings().security_llm_screen,
                   "offender_limit": get_settings().security_offender_limit},
    }


@router.get("/overview")
async def overview() -> dict:
    """Live operational numbers: the in-memory trace ring buffer, MCP servers
    (shared) and per-user Workspace sessions, scheduled-task backlog."""
    from harness.db import tasks as tasks_db
    from harness.mcp.manager import current as mcp_current
    mgr = mcp_current()
    due = await asyncio.to_thread(tasks_db.due_tasks, None, 100) if get_settings().scheduler_enabled else []
    return {
        "metrics": _trace_store.metrics(),
        "recent_traces": _trace_store.recent(10),
        "mcp": [st.as_dict() for st in mgr.status()] if mgr else [],
        "mcp_user_sessions": mgr.user_sessions() if mgr else [],
        "scheduler": {"enabled": get_settings().scheduler_enabled, "due_now": len(due)},
    }
