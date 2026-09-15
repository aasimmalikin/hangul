import asyncio
import json
from fastapi import APIRouter, Depends
from typing import Literal
from pydantic import BaseModel, Field
from pathlib import Path
import structlog
from harness.agent.loop import run_agent
from harness.logging import log
from harness.schemas.run import RunRecord
from harness.providers import get_provider
from harness.prompts.registry import get_prompt
from harness.tools.registry import ToolRegistry
from harness.tools.builtin.calculator import CALCULATOR_TOOL
from harness.tools.builtin.search_docs import SEARCH_DOCS_TOOL
from harness.tools.builtin.web_search import WEB_SEARCH_TOOL
from harness.tools.builtin.ask_user import ASK_USER_TOOL
from harness.tools.builtin.search_docs_session import make_search_docs_tool
from harness.tools.builtin.filesystem_session import wrap_filesystem_tool
from harness.tools.builtin.recall import make_recall_tool
from harness.tools.builtin.remember import make_remember_tool
from harness.tools.builtin.recall_episodes import make_recall_episodes_tool
from harness.cache.keys import answer_key
from harness.cache.redis_cache import RedisCache
from harness.policy.policy import ToolPolicy
from harness.policy.tiers import Tier
from harness.policy.audit import AuditLog
from harness.checkpoint.store import CheckpointStore
from harness.obs.tracing import Trace, cost_usd
from harness.obs.trace_store import TraceStore

from harness.api.auth import get_current_user
from harness.api.concurrency import run_slot
from harness.db.ledger import record_transaction
from decimal import Decimal

from dataclasses import dataclass

from harness.db.memory import profile_text
from harness.db.episodes import store_episode

_audit = AuditLog()
_store = CheckpointStore()
_trace_store = TraceStore()
_policy = ToolPolicy(tiers={
    "calculator": Tier.SAFE,
    "search_docs": Tier.SAFE,
    "web_search": Tier.SAFE,
    "ask_user": Tier.ELICIT,
    "filesystem__read_file": Tier.SAFE,
    "filesystem__read_text_file": Tier.SAFE,
    "filesystem__read_media_file": Tier.SAFE,
    "filesystem__read_multiple_files": Tier.SAFE,
    "filesystem__list_directory": Tier.SAFE,
    "filesystem__list_directory_with_sizes": Tier.SAFE,
    "filesystem__directory_tree": Tier.SAFE,
    "filesystem__get_file_info": Tier.SAFE,
    "filesystem__search_files": Tier.SAFE,
    "filesystem__list_allowed_directories": Tier.SAFE,
    "filesystem__write_file": Tier.DESTRUCTIVE,
    "filesystem__edit_file": Tier.DESTRUCTIVE,
    "filesystem__create_directory": Tier.DESTRUCTIVE,
    "filesystem__move_file": Tier.DESTRUCTIVE,
    "recall": Tier.SAFE,
    "remember": Tier.SAFE,
    "recall_episodes": Tier.SAFE,
})


router = APIRouter()
_registry = ToolRegistry()
_registry.registry(CALCULATOR_TOOL)
_registry.registry(SEARCH_DOCS_TOOL)
_registry.registry(WEB_SEARCH_TOOL)
_registry.registry(ASK_USER_TOOL)

_cache = RedisCache()

DOCS_ONLY_INSTRUCTION = ("\n\nYou are in DOCUMENTS-ONLY mode. You have exactly one tool: search_docs. "
    "For EVERY question you MUST immediately call the search_docs tool with a query "
    "derived from the question. Do NOT reply with text like 'let me check' or "
    "'I will look at the documents' first. Your VERY FIRST action must be to call "
    "search_docs. After you receive the search results, answer using ONLY those "
    "results. If the results do not contain the answer, reply exactly: "
    "'I couldn't find that in your document.' Never answer from your own knowledge.")


# Bounds on what a single request may carry. Anything past these is a bug or
# abuse, and either way must not reach the model's context window unchecked.
MAX_QUESTION_CHARS = 8_000
MAX_HISTORY_TURNS = 20
MAX_HISTORY_CHARS = 4_000


class HistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=MAX_HISTORY_CHARS)


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS,
                          description="The user's question.")
    thread_id: str | None = None
    docs_only: bool = False
    # Earlier turns of this conversation, oldest first. The UI owns the
    # transcript; the server treats it as untrusted context and caps it.
    history: list[HistoryMessage] = Field(default_factory=list, max_length=MAX_HISTORY_TURNS)


class AskResponse(BaseModel):
    answer: str
    run_id: str
    prompt_version: str
    steps: int
    stopped_reason: str
    cached: bool
    tools_used: list[str] = []
    safety_blocked: list[str] = []
    budget_used: dict = {}
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    resumed_from_step: int = 0
    pending_tool: dict | None = None

@dataclass
class RunOutcome:
    result: object
    run: RunRecord
    prompt_version: object
    model: str
    run_cost: float
    cache_key: str

async def _summarize_thread(result: object, question: str) -> str:
    """Summarize the thread for episodic memory storage."""
    return f"User asked {question}. Assistant answered: {result.answer[:400]}"


# Background bookkeeping tasks. asyncio only keeps a weak reference to a
# task, so hold strong refs until they finish or they can be GC'd mid-flight.
_background: set[asyncio.Task] = set()

def _spawn_bookkeeping(coro) -> None:
    task = asyncio.create_task(coro)
    _background.add(task)
    task.add_done_callback(_background.discard)


async def _finish_run(req: AskRequest, user_id: str, run: RunRecord,
                      result: object, key: str, run_cost: float) -> None:
    """Post-answer bookkeeping: ledger, answer cache, episodic memory."""
    cost = Decimal(str(run_cost))
    if cost > 0:
        try:
            await asyncio.to_thread(
                record_transaction,
                user_id=user_id, amount=-cost, kind="run_cost", thread_id=run.run_id,
            )
        except Exception as e:  # noqa: BLE001
            log.warning("ledger write failed", error=str(e))

    try:
        await _cache.set(key, json.dumps({
            "answer": result.answer,
            "steps": result.steps,
            "stopped_reason": result.stopped_reason,
            "tools_used": result.tools_used,
            "safety_blocked": result.safety_blocked,
            "budget_used": result.budget_used,
        }))
    except Exception as e:  # noqa: BLE001
        log.warning("answer cache write failed", error=str(e))

    if result.pending_tool is None and result.answer:
        try:
            thread_summary = await _summarize_thread(result, req.question)
            await store_episode(user_id, run.run_id, thread_summary)
        except Exception as e:  # noqa: BLE001
            log.warning("episode store failed", error=str(e))

async def _build_and_run(req: AskRequest, user_id: str, on_event=None) -> RunOutcome:
    prompt_version = get_prompt("system_agent")
    model = get_provider().model
    run = RunRecord(model=model, prompt_version=prompt_version.version)

    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(run_id=run.run_id, prompt=prompt_version.version)

    log.info("Received question", question=req.question, docs_only=req.docs_only)


    session_registry = ToolRegistry()

    # search_docs is ALWAYS available — it is the one tool docs-only mode needs
    session_registry.registry(make_search_docs_tool(user_id))
    session_registry.registry(make_recall_tool(user_id))
    session_registry.registry(make_remember_tool(user_id))
    session_registry.registry(make_recall_episodes_tool(user_id))

    # the other tools are only added when NOT in docs-only mode
    if not req.docs_only:
        session_registry.registry(CALCULATOR_TOOL)
        session_registry.registry(WEB_SEARCH_TOOL)
        session_registry.registry(ASK_USER_TOOL)
        for t in _registry.list():
            if t.name.startswith("filesystem__"):
                session_registry.registry(wrap_filesystem_tool(t, user_id))
    
    session_dir = (Path("data/sessions") / user_id).resolve()
    session_dir.mkdir(parents=True, exist_ok=True)
    

    session_folder_note = (
         "\n\n=== CRITICAL FILE-PATH RULE (follow exactly) ===\n"
        f"The user's folder is EXACTLY this absolute path: {session_dir}\n"
        "This folder ALREADY EXISTS. For ANY file operation on the user's files "
        "(write, read, list, edit), you MUST use this exact absolute path.\n"
        f"To create a file named notes.txt, call write_file with path='{session_dir}/notes.txt'.\n"
        "You are FORBIDDEN from using a bare filename like 'notes.txt' or an invented "
        f"path like '/mnt/session/'. Always prefix with '{session_dir}/'.\n"
        "Do NOT call create_directory — the folder already exists.\n"
        "=== END RULE ==="
    )
    prompt_text = prompt_version.text + session_folder_note

    # Sync SQLAlchemy call against a remote DB: run it off the event loop so
    # it cannot stall other requests or the SSE flush while it waits.
    try:
        profile = await asyncio.to_thread(profile_text, user_id)
    except Exception as e:  # noqa: BLE001
        # The profile is a nicety; a DB blip must not fail the whole question.
        log.warning("profile load failed", error=str(e))
        profile = ""

    if profile:
        prompt_text = prompt_text + "\n\n=== USER PROFILE ===\n" + profile

    if req.docs_only:
        prompt_text = prompt_text + DOCS_ONLY_INSTRUCTION

    history = [m.model_dump() for m in req.history]
    key = answer_key(
        question=req.question,
        prompt_version=prompt_version.version,
        model=model,
        tool_names=[t.name for t in session_registry.list()],
        session_id = user_id,
        history=history,
        docs_only=req.docs_only,
    )

    trace = Trace(trace_id=run.run_id)


    result = await run_agent(
        question=req.question,
        prompt_text=prompt_text,
        registry=session_registry,
        provider=get_provider(),
        policy=_policy,
        audit=_audit,
        store=_store,
        thread_id=run.run_id,
        trace=trace,
        force_tool_use=req.docs_only,
        on_event=on_event,
        user_id=user_id,
        history=history,
    )


    _trace_store.add(trace, model)

    summary = trace.summary()
    run_cost = cost_usd(model, summary["input_tokens"], summary["output_tokens"])

    # Ledger, answer cache and episodic memory are bookkeeping: nothing the
    # caller receives depends on them, but together they are ~7 serial DB
    # round-trips plus an embedding call. Against a remote Postgres that is
    # several seconds the user would otherwise wait for after the answer has
    # already been produced -- so they run as a background task and the
    # response (or the SSE `done` event) goes out immediately.
    _spawn_bookkeeping(_finish_run(req, user_id, run, result, key, run_cost))

    return RunOutcome(
        result = result,
        run = run,
        prompt_version = prompt_version, 
        model = model,
        run_cost = run_cost, 
        cache_key = key
    )




@router.post("/ask", response_model=AskResponse)
async def ask(req: AskRequest, user: dict = Depends(get_current_user)) -> AskResponse:
    user_id = user["user_id"]

    # cache-hit shortcut stays here — it's specific to the JSON route
    prompt_version = get_prompt("system_agent")
    model = get_provider().model
    session_registry = ToolRegistry()
    session_registry.registry(make_search_docs_tool(user_id))
    if not req.docs_only:
        session_registry.registry(CALCULATOR_TOOL)
        session_registry.registry(WEB_SEARCH_TOOL)
        session_registry.registry(ASK_USER_TOOL)
        for t in _registry.list():
            if t.name.startswith("filesystem__"):
                session_registry.registry(wrap_filesystem_tool(t, user_id))
    key = answer_key(
        question=req.question, prompt_version=prompt_version.version, model=model,
        tool_names=[t.name for t in session_registry.list()], session_id=user_id,
        history=[m.model_dump() for m in req.history], docs_only=req.docs_only,
    )
    cached_raw = await _cache.get(key)
    if cached_raw is not None:
        data = json.loads(cached_raw)
        log.info("cache hit", key=key)
        return AskResponse(
            answer=data["answer"], run_id="cached",
            prompt_version=prompt_version.version,
            steps=data["steps"], stopped_reason=data["stopped_reason"],
            cached=True, tools_used=data.get("tools_used", []),
            safety_blocked=data.get("safety_blocked", []),
            budget_used=data.get("budget_used", {}), cost_usd=0.0, resumed_from_step=0,
        )

    async with run_slot(user_id):
        outcome = await _build_and_run(req, user_id)
    r = outcome.result
    return AskResponse(
        answer=r.answer, run_id=outcome.run.run_id,
        prompt_version=outcome.prompt_version.version,
        steps=r.steps, stopped_reason=r.stopped_reason, cached=False,
        tools_used=r.tools_used, safety_blocked=r.safety_blocked,
        budget_used=r.budget_used, cost_usd=outcome.run_cost,
        input_tokens=r.input_tokens, output_tokens=r.output_tokens,
        resumed_from_step=r.resumed_from_step, pending_tool=r.pending_tool,
    )