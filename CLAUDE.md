# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

An agentic QA harness: a FastAPI backend running a tool-calling agent loop over document retrieval, MCP filesystem tools, and web search, plus two frontends (a Next.js app in `web/`, and a legacy Streamlit demo in `streamlit_app.py`). `README.md`, `Makefile`, and `docs/architecture.md` are empty — this file and the source are the documentation.

## Commands

Backend (Python 3.12, `src` layout, package imported as `harness`):

```bash
uv pip install -e ".[dev]"                       # or: pip install -e ".[dev]"
docker compose up -d                             # postgres:5432 + redis:6379
alembic upgrade head                             # apply migrations
uvicorn harness.api.app:app --reload --port 8000
ruff check src/
```

Frontend (`web/`, Next.js 16 + React 19):

```bash
cd web && npm install && npm run dev    # also: npm run build, npm run lint
```

Retrieval index — must be built before `search_docs` returns anything; writes `data/index.json` and `data/index_version.txt`:

```bash
python -m harness.retrieval.ingest docs
```

Evals and the CI gate (both call the real agent and a real OpenAI judge, so they cost money):

```bash
python run_evals.py     # writes data/eval_runs/eval-<UTC timestamp>.json
python ci_gate.py       # exit 1 if below floors or regressed vs data/eval_baseline.json
```

Container / deploy: `docker build .` then `./start.sh` runs API (8000) + Streamlit (8501) together. `scripts/smoke_test.sh <url>` hits `/healthz` and `/ask`.

Tests:

```bash
.venv/bin/pytest tests/unit                      # backend unit tests (no DB/model needed; fakes)
cd web && npm run test:e2e                       # builds, then Playwright e2e against a fake FastAPI
cd web && npm run test:e2e:only                  # skip the build if .next is current
```

`tests/unit/test_resilience_backend.py` covers approve ownership / double-approve, the per-user in-flight cap, request bounds, history seeding and cache keys. `web/tests/e2e/` runs the production build with a real NextAuth JWT cookie against `tests/e2e/fake-backend.mjs`, a stand-in FastAPI that can be told to fail (question prefixes `APPROVAL`, `ASK`, `DROP`, `ERROR`, `SLOW`, `E500`…; `POST /__control {down:true}`). Needs Playwright's Chromium (`npx playwright install chromium`). `.github/workflows/ci.yml` only lints (non-blocking) and does an import check.

## Architecture

### The agent loop

`src/harness/agent/loop.py` is the core; everything else feeds it. `run_agent()` is a plain async while-loop over provider turns — **not** LangGraph (`agent/graph.py`, `nodes.py`, `state.py` are empty stubs). Each iteration:

1. Loads/creates a `Checkpoint` from `CheckpointStore` keyed by `thread_id` (which is the `run_id`).
2. Calls `provider.chat_stream()` if an `on_event` callback was supplied and the provider supports it, else `provider.chat()`. Every turn is streamed, not just the last, because the text before tool calls is the agent narrating.
3. No tool calls → done. Otherwise appends the assistant message and dispatches each call through `guarded_dispatch`.
4. Saves the checkpoint after each step. Idempotency: `completed_calls` is keyed by `call_key(thread_id, name, args)`, so a resumed run replays a cached result instead of re-executing.

### Human-in-the-loop approval

`ToolPolicy` (`policy/`) maps tool name → `Tier`; `SAFE`/`SENSITIVE` → allow, `DESTRUCTIVE`/`ELICIT` → `NEEDS_APPROVAL`, else deny. The tier table lives in `api/routes/ask.py` (`_policy`).

When the loop hits a call needing approval it does **not** abort mid-message: calls before it run for real, the pending one gets an `[awaiting human approval]` placeholder tool message, later ones get `[not executed]`, and the checkpoint is saved with `status="pending_approval"` and `pending_tool`. This keeps the OpenAI message history valid (every `tool_call` has a matching `tool` reply). `POST /approve` (`routes/approve.py`) then overwrites that placeholder with the real result and calls `run_agent` again on the same `thread_id`.

`ask_user` is the same machinery used for clarification: its handler never really runs — it is tiered `ELICIT` purely so the loop pauses and the UI can render clickable options.

### Per-user isolation (the closure pattern)

Auth is a JWT bearer token (`api/auth.py`); `user_id` is the `sub` claim. Isolation is structural rather than prompt-based, built by wrapping tools per request:

- `make_search_docs_tool(user_id)` — searches that user's uploaded chunks in the in-process `SessionVectorStore`, falling back to the global `data/index.json`.
- `wrap_filesystem_tool(tool, user_id)` — rewrites every path-bearing argument to `data/sessions/<user_id>/<basename>`, so the agent cannot escape its folder no matter what path the model invents. `/approve` re-applies the same forcing before executing an approved write.

A fresh `ToolRegistry` is built per request in `_build_and_run`; the module-level `_registry` in `ask.py` only holds the raw MCP-discovered tools that get wrapped.

`docs_only=True` swaps in a restricted registry (search_docs only) plus `DOCS_ONLY_INSTRUCTION`, and passes `force_tool_use` so the first turn uses `tool_choice="required"`.

### Streaming path

`POST /ask/stream` (`routes/ask_stream.py`) runs the agent as a background task pushing events onto an `asyncio.Queue`, and drains it as SSE (`step`, `text_start`/`text_delta`/`text_end`, `tool_call`, `tool_result`, `approval_required`, `done`). `web/app/api/chat/route.ts` is a BFF that authenticates the NextAuth session, mints a short-lived service JWT with `FASTAPI_JWT_SECRET`, forwards to FastAPI, and translates those events into AI SDK UI-message parts (`data-tool` parts reuse the tool-call id so a result replaces its own running card). Changing an event name means changing it in all three places: `loop.py` emit → `ask_stream.py` → `route.ts`.

`POST /ask` is the non-streaming equivalent and is the only path with the Redis answer cache; the cache key (`cache/keys.py`) hashes question + prompt version + model + tool names + user id, so anything that can change the answer must be in it.

### MCP

Servers are started in the FastAPI lifespan (`api/app.py`), currently only `@modelcontextprotocol/server-filesystem` over stdio scoped to `docs` and `data/sessions`. `MCPManager` namespaces every discovered tool as `<server>__<tool>` and detects shadowing. Node/npx must be available — the Dockerfile installs it for this reason. `mcp/servers.yaml`, `supervisor.py`, and `schema_snapshot.py` are empty placeholders.

### Prompts, evals, observability

- Prompts are files in `prompts/templates/*.txt`; `get_prompt()` versions them by SHA-256 prefix, so editing the text changes `prompt_version` and busts the cache. Prompt version is recorded on every run and every eval report.
- Evals: `data/evalset.jsonl` → `run_eval` → LLM judge scores correctness and faithfulness. `evaluate_gate` blocks on floors of 0.80 and on regressions >0.05 vs `data/eval_baseline.json`. `GET /quality` surfaces the newest report plus the gate verdict. The `evals/` top-level directory is entirely empty stubs — the working code is `src/harness/eval/`.
- Tracing is homegrown (`obs/tracing.py`), using OTel-style span names (`gen_ai.chat`, `gen_ai.tool.execute`). `PRICING` there is keyed by model id and must be updated when `settings.model` changes, or cost comes out as 0. `GET /traces` and `GET /metrics` read the in-memory ring buffer.
- Per-run cost is written to the `transactions` ledger (append-only, `balance_after` denormalized) via `record_transaction`.

## Conventions and traps

- `ToolRegistry.registry(tool)` is the *add* method (not a property), and `Tool.parameter` is singular. Both read like typos; they are the API.
- `Checkpoint.message` (singular) is the full message list.
- Config is pydantic-settings reading root `.env`; field names are lowercase (`openai_api_key`, `database_url`). `get_settings()` is *not* cached, but `get_provider()` and `get_embedder()` are — changing `.env` at runtime won't reach them.
- `SessionVectorStore` is in-process memory with a TTL/LRU, so uploaded documents die with the worker and do not survive multiple replicas.
- `web/` is Next.js 16: middleware is `web/proxy.ts`, not `middleware.ts`. Follow `web/AGENTS.md` and read `node_modules/next/dist/docs/` before writing Next-specific code.
- Frontend theme: every page uses `components/hangul/AppHeader` (+ `SignInModal` if it needs a session) and the `.h-*` classes / `var(--fg|--muted|--surface|--solid-bg…)` tokens from `globals.css`. Tailwind's shadcn tokens are mapped to the same palette. Never hard-code colours. See `docs/notes/2026-09-15-frontend-theme-unification.md`.
- BFF routes (`web/app/api/*`) all go through `web/lib/bff.ts`: same-origin check → session → per-user rate limit → `upstream()` with a timeout; errors are `{detail, code}`. Add new routes the same way. The backend caps runs per user (`api/concurrency.py`) and `threads.user_id` is checked on `/approve` (`CheckpointStore.claim_pending`).
- The chat thread is persisted per **tab** in `sessionStorage` (`hangul:chat:<user id>`): refresh/back/forward restore it, a new tab is a new conversation, tabs never share state. Every completed run ends with a hidden `data-run` part (used by tests as the end-of-run marker; not shown to the user).
- `streamlit_app.py` still authenticates with an `X-Session-ID` header, which the JWT-guarded routes no longer accept; treat it as legacy unless you are updating it.
