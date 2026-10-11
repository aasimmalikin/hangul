"""Run the *real* agent for an eval case. Shared by run_evals.py and the
admin API so a run from the page and a run from the CLI are identical.

Costs real model calls. The tool_selection registry mirrors what /ask gives a
signed-in user (minus per-user memory), under a throwaway eval user so file
writes land in data/sessions/<EVAL_USER_ID> and pause for approval exactly
like production -- the pause is what approval_compliance grades."""

import asyncio
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from harness.agent.loop import run_agent
from harness.api.routes.ask import _audit, _policy, _registry, _store, add_connector_tools
from harness.connectors import tools_for
from harness.eval.catalog import SUITES
from harness.eval.dataset import EvalCase, load_case
from harness.eval.openai_judge import OpenAIJudge
from harness.eval.store import save_report
from harness.eval.suites import run_prompt_injection_suite, run_qa_suite, run_tool_selection_suite
from harness.eval.trajectory import Trajectory, TrajectoryRecorder
from harness.obs.tracing import Trace
from harness.prompts.registry import get_prompt
from harness.providers import get_provider
from harness.security import get_guard
from harness.tools.base import Tool
from harness.tools.builtin.ask_user import ASK_USER_TOOL
from harness.tools.builtin.calculator import CALCULATOR_TOOL
from harness.tools.builtin.files import make_create_file_tool
from harness.tools.builtin.my_files import make_my_files_tool
from harness.tools.builtin.search_docs import SEARCH_DOCS_TOOL
from harness.tools.builtin.vault_request import build_vault_tools
from harness.tools.builtin.web_search import WEB_SEARCH_TOOL
from harness.tools.registry import ToolRegistry

EVAL_USER_ID = "0"          # no such user: memory/vault lookups find nothing, file writes are sandboxed
DATASETS = {"qa": Path("data/evalset.jsonl"), "tool_selection": Path("data/evalsets/tool_selection.jsonl"),
            "prompt_injection": Path("data/evalsets/prompt_injection.jsonl"),
            "business": Path("data/evalsets/business.jsonl")}


@asynccontextmanager
async def _mcp_tools_available():
    """Inside the API the lifespan already discovered the MCP tools into
    ``_registry`` and built the vault; from the CLI nothing has, so bring both
    up for the duration of the run (and tear them down after)."""
    from harness import vault as vault_mod
    from harness.config import get_settings
    from harness.mcp.config import load_server_configs
    from harness.mcp.manager import MCPManager
    from harness.vault.bootstrap import build_vault, shutdown_vault

    own_vault = vault_mod.current() is None
    if own_vault:
        await build_vault(get_settings(), audit=_audit)
    try:
        if any(t.name.startswith("filesystem__") for t in _registry.list()):
            yield
            return
        async with MCPManager(load_server_configs()) as mgr:
            mgr.register_into(_registry)
            yield
    finally:
        if own_vault:
            await shutdown_vault()


def qa_registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.registry(SEARCH_DOCS_TOOL)
    reg.registry(CALCULATOR_TOOL)
    return reg


async def full_registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.registry(SEARCH_DOCS_TOOL)
    reg.registry(CALCULATOR_TOOL)
    reg.registry(WEB_SEARCH_TOOL)
    reg.registry(ASK_USER_TOOL)
    reg.registry(make_my_files_tool(EVAL_USER_ID))
    reg.registry(make_create_file_tool(EVAL_USER_ID))
    for t in await build_vault_tools(EVAL_USER_ID, None):
        reg.registry(t)
    return reg


async def business_registry() -> ToolRegistry:
    """What a shop owner's run starts from: the full registry plus the everyday and
    business tools (not plan-gated: the eval user has no plan)."""
    from harness.tools.builtin.daily import build_daily_tools
    reg = await full_registry()
    for t in build_daily_tools(EVAL_USER_ID, "Asia/Kolkata"):
        reg.registry(t)
    return reg


def ensure_eval_shop() -> None:
    """The eval user's shop, the same every run: a café with five weeks of sales (so the
    forecast is ready) and three customers (Riya's birthday in 3 days, Sana away 40 days).
    Cases may log today's sales on top; a re-run logs over them."""
    from datetime import timedelta

    from harness.db import customers as customers_db
    from harness.db import sales as sales_db
    from harness.sales import service
    today = service.local_today(EVAL_USER_ID)
    shops = [b for b in sales_db.list_for(EVAL_USER_ID) if not b["paused"]]
    b = shops[0] if shops else sales_db.create(EVAL_USER_ID, name="Chai Point", kind="cafe", city="Pune")
    have = {d["day"] for d in sales_db.days_for(b["id"], today - timedelta(days=40))}
    weekday = (14200, 13100, 13600, 14400, 16800, 21500, 19800)
    for k in range(1, 36):
        d = today - timedelta(days=k)
        if d.isoformat() not in have:
            sales_db.log_day(b["id"], d, sales=weekday[d.weekday()] + (k % 5) * 150, bills=40 + (k % 7), source="import")
    if not customers_db.find(EVAL_USER_ID, "Riya"):
        soon = today + timedelta(days=3)
        customers_db.add(EVAL_USER_ID, "Riya", "98765 43210", birthday=f"{soon.day}/{soon.month}", note="masala chai")
        customers_db.add(EVAL_USER_ID, "Aman", "98000 00001")
        sana, _ = customers_db.add(EVAL_USER_ID, "Sana", "98000 00002")
        for gap in (60, 52, 46, 40):
            customers_db.visit(EVAL_USER_ID, sana["id"], today - timedelta(days=gap))


def _with_connectors(base: ToolRegistry, keys: list[str]) -> ToolRegistry:
    reg = ToolRegistry()
    for t in base.list():
        reg.registry(t)
    add_connector_tools(reg, keys)
    return reg


def _poisoned(base: ToolRegistry, poison: dict) -> ToolRegistry:
    """Same tools, except the poisoned one appends the attack payload to its
    real result -- what a compromised document / page / API would do."""
    tool_name, payload = poison.get("tool"), poison.get("payload", "")
    reg = ToolRegistry()
    for t in base.list():
        if t.name != tool_name:
            reg.registry(t)
            continue
        original = t.handler

        def make(orig):
            async def handler(**kwargs) -> str:
                try:
                    real = await orig(**kwargs)
                except Exception as e:  # noqa: BLE001 - the payload still arrives
                    real = f"(tool error: {type(e).__name__})"
                return f"{real}\n\n{payload}"
            return handler
        reg.registry(Tool(name=t.name, description=t.description, parameter=t.parameter, handler=make(original)))
    return reg


def _prompt_for(case: EvalCase) -> str:
    text = get_prompt("system_agent").text
    session_dir = (Path("data/sessions") / EVAL_USER_ID).resolve()
    return text + f"\n\nThe user's folder is: {session_dir}"


async def run_case(case: EvalCase, registry: ToolRegistry, *, model: str, shop: bool = False) -> Trajectory:
    """``shop``: run as a shop owner does -- the shop block in the prompt and the
    registry narrowed to the core tools plus what the question needs (agent/tool_router.py)."""
    rec = TrajectoryRecorder()
    tid = "eval-" + uuid.uuid4().hex[:12]
    prompt = _prompt_for(case)
    block = ""
    if shop:
        from harness.agent import tool_router
        from harness.sales import shop_state
        shop_state.forget(EVAL_USER_ID)                  # earlier cases may have logged sales
        block = await shop_state.shop_block(EVAL_USER_ID, timeout=None)      # graded with it, however slow the DB
        prompt += ("\n\n" + block) if block else ""
        recent = {(tc.get("function") or {}).get("name") for m in case.history for tc in (m.get("tool_calls") or [])}
        registry = tool_router.narrow(registry, case.question, recent - {None})
    if case.connectors:
        # same as /ask: the connector's tools plus its prompt note, per case
        registry = _with_connectors(registry, case.connectors)
        prompt += "\n\n=== CONNECTORS ===\n" + add_connector_tools(ToolRegistry(), case.connectors)
    if case.poison:
        registry = _poisoned(registry, case.poison)
    result = await run_agent(
        question=case.question, prompt_text=prompt, registry=registry,
        provider=get_provider(), policy=_policy, audit=_audit, store=_store, thread_id=tid,
        trace=Trace(trace_id=tid), on_event=rec.on_event, history=case.history or None,
        user_id=EVAL_USER_ID, security=get_guard(),
    )
    cp = await asyncio.to_thread(_store.load, tid)
    if cp is not None:
        rec.attach_results(tid, cp.completed_calls)
    traj = rec.finish(result, model)
    traj.context = block
    return traj


async def qa_run_fn(question: str) -> tuple[str, str]:
    tid = "eval-" + uuid.uuid4().hex[:12]
    result = await run_agent(
        question=question, prompt_text=get_prompt("system_agent").text, registry=qa_registry(),
        provider=get_provider(), policy=_policy, audit=_audit, store=_store, thread_id=tid,
        trace=Trace(trace_id=tid),
    )
    return result.answer, result.retrieved_context


def current_index_version() -> str:
    p = Path("data/index_version.txt")
    return p.read_text().strip() if p.exists() else "unknown"


async def run_suite(suite: str, *, save: bool = True, judge=None, limit: int | None = None,
                    ids: list[str] | None = None) -> tuple[dict, Path | None]:
    if suite not in SUITES:
        raise ValueError(f"unknown suite {suite!r}; known: {sorted(SUITES)}")
    cases = load_case(DATASETS[suite])
    if ids:
        cases = [c for c in cases if c.id in set(ids)]
    if limit:
        cases = cases[:limit]
    model = get_provider().model
    prompt_version = get_prompt("system_agent").version
    judge = judge or OpenAIJudge()

    if suite == "qa":
        report = await run_qa_suite(cases, qa_run_fn, judge, prompt_version=prompt_version,
                                    index_version=current_index_version(), model=model)
    else:
        async with _mcp_tools_available():
            shop = suite == "business"
            if shop:
                await asyncio.to_thread(ensure_eval_shop)
            registry = await (business_registry() if shop else full_registry())
            schemas = {t.name: t.parameter for t in registry.list()}
            if shop:
                from harness.agent import tool_router
                schemas["more_tools"] = tool_router.narrow(registry, "").get("more_tools").parameter
            # connector tools are only in a case's registry when that case enables
            # them, but the hallucination grader must know they are real tools
            for keys in {tuple(c.connectors) for c in cases if c.connectors}:
                schemas.update({t.name: t.parameter for t in tools_for(list(keys), _registry.list())[0]})

            async def run_fn(case: EvalCase) -> Trajectory:
                return await run_case(case, registry, model=model, shop=shop)

            if suite == "prompt_injection":
                report = await run_prompt_injection_suite(cases, run_fn, judge, prompt_version=prompt_version,
                                                          model=model)
            else:
                report = await run_tool_selection_suite(cases, run_fn, schemas, judge,
                                                        prompt_version=prompt_version, model=model)
    path = save_report(suite, report) if save else None
    return report, path
