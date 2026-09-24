import asyncio
import hashlib
import json
from fastapi import APIRouter, Depends, HTTPException
from typing import Literal
from pydantic import BaseModel, Field
from pathlib import Path
import structlog
from harness.agent.loop import run_agent
from harness.logging import log
from harness.schemas.run import RunRecord
from harness.providers import provider_for
from harness.providers.registry import ModelSpec, Effort, resolve, budget_for
from harness.prompts.registry import get_prompt
from harness.tools.registry import ToolRegistry
from harness.tools.builtin.calculator import CALCULATOR_TOOL
from harness.tools.builtin.search_docs import SEARCH_DOCS_TOOL
from harness.tools.builtin.web_search import WEB_SEARCH_TOOL
from harness.tools.builtin.ask_user import ASK_USER_TOOL
from harness.tools.builtin.search_docs_session import make_search_docs_tool
from harness.tools.builtin.filesystem_session import wrap_filesystem_tool
from harness.tools.builtin.vault_request import build_vault_tools
from harness.connectors import tools_for, validate_keys
from harness.security import get_guard
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
from harness.api.conversation_lock import conversation_slot
from harness.agent import context as ctx
from harness.db.conversations import (
    append_messages,
    bind_settings,
    create_conversation,
    get_conversation,
    load_messages,
    save_security,
    set_summary,
    set_title,
)
from harness.db.ledger import record_transaction
from decimal import Decimal

from dataclasses import dataclass

from harness.db.memory import profile_text
from harness.db.episodes import store_episode
from harness.db.settings import get_settings as user_prefs
from harness.db.settings import prompt_block as prefs_block

_audit = AuditLog()
_store = CheckpointStore()
_trace_store = TraceStore()
_policy = ToolPolicy(tiers={
    "calculator": Tier.SAFE,
    "search_docs": Tier.SAFE,
    "web_search": Tier.SAFE,
    "ask_user": Tier.ELICIT,
    "vault_request": Tier.SENSITIVE,     # reads run under standing consent
    "vault_mutate": Tier.DESTRUCTIVE,    # every write pauses for approval
    "arxiv_search": Tier.SAFE,           # Research connector (read-only public API)
    "arxiv_paper": Tier.SAFE,
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
}, patterns=[
    # Google Workspace bundle (official MCP servers): anything that sends,
    # creates, changes or deletes pauses for approval; reads run.
    ("gmail__*send*", Tier.DESTRUCTIVE), ("gmail__*delete*", Tier.DESTRUCTIVE), ("gmail__*trash*", Tier.DESTRUCTIVE),
    ("gmail__*modify*", Tier.DESTRUCTIVE), ("gmail__create_*", Tier.DESTRUCTIVE), ("gmail__*draft*", Tier.SENSITIVE),
    ("calendar__*create*", Tier.DESTRUCTIVE), ("calendar__*update*", Tier.DESTRUCTIVE),
    ("calendar__*delete*", Tier.DESTRUCTIVE), ("calendar__*insert*", Tier.DESTRUCTIVE),
    ("drive__*delete*", Tier.DESTRUCTIVE), ("drive__*upload*", Tier.DESTRUCTIVE), ("drive__*create*", Tier.DESTRUCTIVE),
    ("drive__*share*", Tier.DESTRUCTIVE), ("drive__*permission*", Tier.DESTRUCTIVE), ("drive__*move*", Tier.DESTRUCTIVE),
    ("docs__*create*", Tier.DESTRUCTIVE), ("docs__*update*", Tier.DESTRUCTIVE), ("docs__*insert*", Tier.DESTRUCTIVE),
    ("docs__*replace*", Tier.DESTRUCTIVE), ("docs__*delete*", Tier.DESTRUCTIVE), ("docs__*append*", Tier.DESTRUCTIVE),
    ("gmail__*", Tier.SENSITIVE), ("calendar__*", Tier.SENSITIVE), ("drive__*", Tier.SENSITIVE), ("docs__*", Tier.SENSITIVE),
])


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
    # The conversation to continue (conversations.id). Absent = start a new one,
    # whose id comes back on the response and the SSE `done` event. This is what
    # makes a chat resumable and lets one user hold several at once.
    conversation_id: str | None = Field(default=None, max_length=64)
    docs_only: bool = False
    # DEPRECATED: superseded by conversation_id and ignored when one is given.
    # The server owns the transcript now -- and stores tool results too, which
    # this never carried. Kept for stateless callers (streamlit_app.py) until
    # they move over.
    history: list[HistoryMessage] = Field(default_factory=list, max_length=MAX_HISTORY_TURNS)
    # Which model to run and how hard it should think (see providers.registry).
    # None = the configured default. Validated by `resolve()` -> 422.
    model: str | None = Field(default=None, max_length=64)
    effort: str | None = Field(default=None, max_length=16)
    # Connectors switched on for this conversation ("+ → Connectors" in the
    # UI), e.g. ["arxiv"]. Validated against harness.connectors -> 422.
    connectors: list[str] = Field(default_factory=list, max_length=8)
    # "research": a multi-step, citation-required run with a bigger budget
    mode: Literal["default", "research"] = "default"


RESEARCH_INSTRUCTION = (
    "\n\n=== DEEP RESEARCH MODE ===\n"
    "The user wants a researched answer, not a quick one. Work in stages: (1) write a 2-4 point plan "
    "of what must be found; (2) run several distinct searches -- the user's documents, the web, and arXiv "
    "when the topic is scientific -- and read the most relevant results; (3) reconcile conflicting sources "
    "and note uncertainty; (4) answer with numbered citations [1], [2]... and finish with a 'Sources' list "
    "giving each citation's title and URL/id. Prefer primary sources. Do not stop after one search.\n"
    "=== END ==="
)


def connectors_or_422(keys: list[str]) -> list[str]:
    try:
        return validate_keys(keys)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


def add_connector_tools(registry: ToolRegistry, keys: list[str], user_id: str | None = None) -> str:
    """Register the enabled connectors' tools; returns the prompt note.
    Per-user MCP connectors (the Google bundle) must have been prepared with
    ``prepare_connectors`` first so their tools are discovered."""
    from harness.mcp.manager import current as mcp_current
    tools, note, _ = tools_for(keys, _registry.list(), user_id=user_id, manager=mcp_current())
    for t in tools:
        registry.registry(t)
    return note


async def prepare_connectors(keys: list[str], user_id: str) -> list[str]:
    """Open this user's sessions on per-user MCP connectors. A connector the
    user has not connected is dropped with a note (the run still proceeds)."""
    from harness.connectors.registry import prepare
    return await prepare(keys, user_id)


def resolve_or_422(model: str | None, effort: str | None) -> tuple[ModelSpec, Effort | None]:
    try:
        return resolve(model, effort)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


class AskResponse(BaseModel):
    answer: str
    run_id: str
    # The conversation this run belongs to: echoed back so a client that sent
    # none can keep using the one the server created.
    conversation_id: str | None = None
    prompt_version: str
    model: str = ""
    effort: str | None = None
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
    # what the prompt-injection layers flagged (harness.security)
    security_events: list[dict] = []

@dataclass
class RunOutcome:
    result: object
    run: RunRecord
    prompt_version: object
    model: str
    run_cost: float
    cache_key: str
    effort: str | None = None
    conversation_id: str | None = None

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
                      result: object, key: str, run_cost: float, *,
                      conversation_id: str | None = None,
                      cacheable: bool = True) -> None:
    """Post-answer bookkeeping: ledger, answer cache, episodic memory.

    ``cacheable`` is False once the conversation has earlier turns: the answer
    then depends on the whole transcript, which the key does not hash, so
    caching it would serve it to a different question's context.

    The episode is keyed by the CONVERSATION, not the run. It used to be keyed
    by run_id with an empty title, which made a titleless duplicate rail row per
    answer; the rail reads conversations now and the episode is purely the
    embedding behind ``recall_episodes``.
    """
    cost = Decimal(str(run_cost))
    if cost > 0:
        try:
            await asyncio.to_thread(
                record_transaction,
                user_id=user_id, amount=-cost, kind="run_cost", thread_id=run.run_id,
            )
        except Exception as e:  # noqa: BLE001
            log.warning("ledger write failed", error=str(e))

    if cacheable:
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
            # One episode per conversation (upserted on (user_id, thread_id)),
            # titled -- not one per run with a blank title.
            await store_episode(user_id, conversation_id or run.run_id,
                                thread_summary, title=req.question[:200])
        except Exception as e:  # noqa: BLE001
            log.warning("episode store failed", error=str(e))

async def _persist_turn(conversation_id: str, run_id: str, question: str) -> None:
    """Append this run's messages to the conversation transcript.

    Reads the final checkpoint rather than tracking the list in the route: the
    loop owns the message list, and after a resume via /approve the checkpoint
    is the only place the whole turn exists. ``persisted_upto`` says where the
    unpersisted part starts, so appending twice adds nothing.

    Also carries the run's taint up to the conversation, which is what makes a
    poisoned chat stay poisoned on the next turn.
    """
    try:
        cp = await asyncio.to_thread(_store.load, run_id)
        if cp is None:
            log.warning("no checkpoint to persist", run_id=run_id)
            return
        new_messages = cp.message[cp.persisted_upto:]
        if new_messages:
            await asyncio.to_thread(append_messages, conversation_id, run_id, new_messages)
            cp.persisted_upto = len(cp.message)
            await asyncio.to_thread(_store.save, cp)
        if question:
            # Names the conversation for the Chats rail; only fills a blank one.
            await asyncio.to_thread(set_title, conversation_id, question)
        if cp.security:
            await asyncio.to_thread(save_security, conversation_id, cp.security)
    except Exception as e:  # noqa: BLE001
        # The answer is already produced; losing the append costs the next turn
        # its context, which is bad, but failing the response is worse.
        log.error("transcript append failed", conversation_id=conversation_id,
                  run_id=run_id, error=str(e))


async def _build_and_run(req: AskRequest, user_id: str, on_event=None) -> RunOutcome:
    security = get_guard()
    if security.is_throttled(user_id):
        # repeat offender: too many injection-like messages in the window
        raise HTTPException(status_code=429, detail="Too many suspicious requests; try again later.",
                            headers={"Retry-After": str(security.offender_window_s), "X-Reason": "security_throttled"})
    prompt_version = get_prompt("system_agent")

    # The conversation comes first: its stored settings are the defaults for
    # anything this request left unset, which is what makes resuming a chat on
    # another device behave the same as it did on the first.
    conv = None
    if req.conversation_id:
        conv = await asyncio.to_thread(get_conversation, req.conversation_id, user_id)
        if conv is None:
            # A conversation that is not the caller's is indistinguishable from
            # one that does not exist (as in deactivate_episode).
            raise HTTPException(status_code=404, detail="No such conversation.")
        if req.history:
            log.warning("history ignored: conversation_id given",
                        conversation_id=req.conversation_id)

    spec, effort = resolve_or_422(req.model or (conv.model if conv else None),
                                  req.effort or (conv.effort if conv else None))
    model = spec.id
    budget = budget_for(effort)
    run = RunRecord(model=model, prompt_version=prompt_version.version)

    # Everything below reads these rather than req.*, so a resumed conversation
    # keeps the tools and mode it was started with when the client sends none.
    docs_only = req.docs_only or bool(conv and conv.docs_only)
    mode = req.mode if req.mode != "default" else (conv.mode if conv else "default")

    # No conversation given: start one, so the very first turn is already
    # durable and the client gets an id back without a second round trip.
    # A failure here is not fatal -- the run degrades to the stateless path.
    if conv is None:
        try:
            new_id = await asyncio.to_thread(
                create_conversation, user_id, model=model, effort=effort,
                connectors=list(req.connectors), mode=mode, docs_only=docs_only)
            conv = await asyncio.to_thread(get_conversation, new_id, user_id)
        except Exception as e:  # noqa: BLE001
            log.warning("conversation create failed; running stateless", error=str(e))

    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(run_id=run.run_id, prompt=prompt_version.version)

    log.info("Received question", question=req.question, docs_only=docs_only,
             model=model, effort=effort)


    session_registry = ToolRegistry()

    # search_docs is ALWAYS available — it is the one tool docs-only mode needs
    session_registry.registry(make_search_docs_tool(user_id))
    session_registry.registry(make_recall_tool(user_id))
    session_registry.registry(make_remember_tool(user_id))
    session_registry.registry(make_recall_episodes_tool(user_id))

    # the other tools are only added when NOT in docs-only mode
    if not docs_only:
        session_registry.registry(CALCULATOR_TOOL)
        session_registry.registry(WEB_SEARCH_TOOL)
        session_registry.registry(ASK_USER_TOOL)
        for t in _registry.list():
            if t.name.startswith("filesystem__"):
                session_registry.registry(wrap_filesystem_tool(t, user_id))
        for t in await build_vault_tools(user_id, run.run_id):
            session_registry.registry(t)
    connectors = connectors_or_422(req.connectors or (list(conv.connectors) if conv else []))
    if mode == "research" and not docs_only and "arxiv" not in connectors:
        connectors = [*connectors, "arxiv"]          # research always has the literature tool
    connector_note = ""
    if not docs_only and connectors:
        problems = await prepare_connectors(connectors, user_id)
        connector_note = add_connector_tools(session_registry, connectors, user_id)
        if problems:
            connector_note += "\n" + "\n".join(problems)
    
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

    # personalisation: name, timezone/local time, tone, custom instructions
    prefs = None
    try:
        prefs = await asyncio.to_thread(user_prefs, user_id)
        prompt_text = prompt_text + "\n\n" + prefs_block(prefs)
    except Exception as e:  # noqa: BLE001 - a DB blip must not fail the question
        log.warning("user settings load failed", error=str(e))

    if docs_only:
        prompt_text = prompt_text + DOCS_ONLY_INSTRUCTION
    if mode == "research":
        prompt_text = prompt_text + RESEARCH_INSTRUCTION
        budget = budget.__class__(max_steps=budget.max_steps * 2, max_tokens=budget.max_tokens * 2)
    if connector_note:
        prompt_text = prompt_text + "\n\n=== CONNECTORS ===\n" + connector_note

    # ---------------------------------------------------------------- context
    # With a conversation, the server owns the transcript: the seed comes from
    # conversation_messages (all roles, so earlier tool results are still
    # there), windowed to the budget, with anything older folded into the
    # conversation's rolling summary. Without one, fall back to the client's
    # `history` -- text-only, the pre-conversation behaviour.
    history = [m.model_dump() for m in req.history]
    initial_messages = None
    persisted_upto = 0
    conversation_id = conv.id if conv else None
    started_empty = True

    if conv is not None:
        try:
            rows = await asyncio.to_thread(load_messages, conv.id, conv.summary_through_seq)
        except Exception as e:  # noqa: BLE001
            # Losing the transcript would silently answer without context, which
            # is worse than failing loudly on a question the user can retry.
            log.error("transcript load failed", conversation_id=conv.id, error=str(e))
            raise HTTPException(status_code=503, detail="Could not load this conversation.")
        started_empty = not rows and conv.next_seq == 0
        initial_messages, dropped = ctx.build_messages(
            prompt_text=prompt_text, question=req.question,
            summary=conv.summary_text, history=rows,
            token_budget=budget.max_tokens,
        )
        # The seed's last element is the new question, and everything before it
        # was replayed out of the transcript -- so persistence starts there.
        persisted_upto = len(initial_messages) - 1
        problem = ctx.validate(initial_messages)
        if problem:
            # Would be a provider 400. Fall back to no history rather than fail:
            # a context-less answer beats no answer, and the log names the bug.
            log.error("built an invalid message list", conversation_id=conv.id, problem=problem)
            initial_messages, dropped = ctx.build_messages(
                prompt_text=prompt_text, question=req.question,
                summary=conv.summary_text, history=[], token_budget=budget.max_tokens)
            persisted_upto = len(initial_messages) - 1
        if dropped:
            # Older turns leave the window: fold them into the summary once, so
            # the cost is paid when the window advances and not every turn.
            through = dropped[-1].seq
            text = await ctx.compact(prior_summary=conv.summary_text, dropped=dropped)
            if text and text != conv.summary_text:
                await asyncio.to_thread(set_summary, conv.id, text, through)

    key = answer_key(
        question=req.question,
        prompt_version=prompt_version.version,
        model=model,
        tool_names=[t.name for t in session_registry.list()],
        session_id = user_id,
        history=history,
        docs_only=docs_only,
        effort=effort,
        mode=mode,
        prefs_version=hashlib.sha256(json.dumps(prefs.as_dict(), sort_keys=True).encode()).hexdigest()[:12] if prefs else "",
    )

    trace = Trace(trace_id=run.run_id)

    async def _go():
        return await run_agent(
            question=req.question,
            prompt_text=prompt_text,
            registry=session_registry,
            provider=provider_for(spec, effort),
            policy=_policy,
            audit=_audit,
            store=_store,
            thread_id=run.run_id,
            trace=trace,
            force_tool_use=docs_only,
            max_steps=budget.max_steps,
            max_tokens=budget.max_tokens,
            on_event=on_event,
            user_id=user_id,
            history=history,
            initial_messages=initial_messages,
            connectors=connectors,
            security=security,
            # Taint is a property of the conversation, not one run: a chat that
            # already ingested a poisoned document is still suspect this turn.
            security_state=dict(conv.security) if conv is not None else None,
            # The canary must be stable across the conversation's turns: a
            # per-run one would leave stale canaries in replayed messages that
            # guard_output no longer strips.
            security_scope=conversation_id,
            conversation_id=conversation_id,
            persisted_upto=persisted_upto,
        )

    if conversation_id is None:
        result = await _go()
    else:
        # One run at a time per conversation, or the message list interleaves
        # and the NEXT turn is the one the provider rejects.
        async with conversation_slot(conversation_id, run.run_id):
            result = await _go()

    for ev in result.security_events:
        _audit.record_security(run_id=run.run_id, user_id=user_id, **ev)

    if conversation_id is not None:
        # The transcript is correctness, not bookkeeping: if this lost a race
        # with the user's next turn it would silently drop a turn, so it is
        # awaited here rather than spawned with the ledger and cache writes.
        await _persist_turn(conversation_id, run.run_id, req.question)
        await asyncio.to_thread(bind_settings, conversation_id, model=model,
                                effort=effort, connectors=connectors, mode=mode)


    _trace_store.add(trace, model)

    summary = trace.summary()
    run_cost = cost_usd(model, summary["input_tokens"], summary["output_tokens"])

    # Ledger, answer cache and episodic memory are bookkeeping: nothing the
    # caller receives depends on them, but together they are ~7 serial DB
    # round-trips plus an embedding call. Against a remote Postgres that is
    # several seconds the user would otherwise wait for after the answer has
    # already been produced -- so they run as a background task and the
    # response (or the SSE `done` event) goes out immediately.
    _spawn_bookkeeping(_finish_run(req, user_id, run, result, key, run_cost,
                                   conversation_id=conversation_id,
                                   cacheable=started_empty))

    return RunOutcome(
        result = result,
        run = run,
        prompt_version = prompt_version, 
        model = model,
        run_cost = run_cost,
        cache_key = key,
        effort = effort,
        conversation_id = conversation_id,
    )




@router.post("/ask", response_model=AskResponse)
async def ask(req: AskRequest, user: dict = Depends(get_current_user)) -> AskResponse:
    user_id = user["user_id"]

    # cache-hit shortcut stays here — it's specific to the JSON route
    prompt_version = get_prompt("system_agent")
    spec, effort = resolve_or_422(req.model, req.effort)
    model = spec.id
    session_registry = ToolRegistry()
    session_registry.registry(make_search_docs_tool(user_id))
    if not req.docs_only:
        session_registry.registry(CALCULATOR_TOOL)
        session_registry.registry(WEB_SEARCH_TOOL)
        session_registry.registry(ASK_USER_TOOL)
        for t in _registry.list():
            if t.name.startswith("filesystem__"):
                session_registry.registry(wrap_filesystem_tool(t, user_id))
        for t in await build_vault_tools(user_id, None):
            session_registry.registry(t)
        add_connector_tools(session_registry, connectors_or_422(req.connectors), user_id)
    prefs_v = ""
    try:
        prefs_v = hashlib.sha256(json.dumps((await asyncio.to_thread(user_prefs, user_id)).as_dict(), sort_keys=True).encode()).hexdigest()[:12]
    except Exception:  # noqa: BLE001
        pass
    key = answer_key(
        question=req.question, prompt_version=prompt_version.version, model=model,
        tool_names=[t.name for t in session_registry.list()], session_id=user_id,
        history=[m.model_dump() for m in req.history], docs_only=req.docs_only, mode=req.mode, prefs_version=prefs_v,
        effort=effort,
    )
    # The cache only ever serves a FIRST turn. Past that the answer depends on
    # the transcript, which the key does not hash -- a hit would be an answer
    # from a different context. _finish_run applies the same rule on the write.
    cached_raw = None
    if req.conversation_id is None:
        cached_raw = await _cache.get(key)
    if cached_raw is not None:
        data = json.loads(cached_raw)
        log.info("cache hit", key=key)
        return AskResponse(
            answer=data["answer"], run_id="cached", conversation_id=None,
            prompt_version=prompt_version.version, model=model, effort=effort,
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
        conversation_id=outcome.conversation_id,
        prompt_version=outcome.prompt_version.version,
        model=outcome.model, effort=outcome.effort,
        steps=r.steps, stopped_reason=r.stopped_reason, cached=False,
        tools_used=r.tools_used, safety_blocked=r.safety_blocked,
        budget_used=r.budget_used, cost_usd=outcome.run_cost,
        input_tokens=r.input_tokens, output_tokens=r.output_tokens,
        resumed_from_step=r.resumed_from_step, pending_tool=r.pending_tool,
        security_events=r.security_events,
    )