# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Hangul (`hangul-harness`), an agentic QA harness: a FastAPI backend running a tool-calling agent loop over document retrieval, MCP filesystem tools, and web search, plus two frontends (a Next.js app in `web/`, and a legacy Streamlit demo in `streamlit_app.py`). `README.md`, `Makefile`, and `docs/architecture.md` are empty — this file and the source are the documentation.

## Commands

Backend (Python 3.12, `src` layout, package imported as `harness`):

```bash
uv pip install -e ".[dev]"                       # or: pip install -e ".[dev]"
docker compose up -d                             # postgres:5432 + redis:6379
alembic upgrade head                             # apply migrations (incl. vault_credentials / vault_consents)
uvicorn harness.api.app:app --reload --port 8000
ruff check src/
```

Frontend (`web/`, Next.js 16 + React 19):

```bash
cd web && npm install && npm run dev    # also: npm run build, npm run lint
```

Retrieval index — must be built before `search_docs` returns anything. Embeds `docs/*.txt` into the `document_chunks` table in Postgres (`user_id IS NULL` = the shared corpus) and writes `data/index_version.txt`:

```bash
python -m harness.retrieval.ingest docs          # -> pgvector
python -m harness.retrieval.ingest docs --backend json   # legacy data/index.json, for a machine with no DB
```

Evals and the CI gate (both call the real agent and a real OpenAI judge, so they cost money):

```bash
python run_evals.py                              # qa suite -> data/eval_runs/eval-<UTC timestamp>.json
python run_evals.py --suite tool_selection --limit 5   # -> data/eval_runs/tool_selection-<stamp>.json
python ci_gate.py       # exit 1 if below floors or regressed vs data/eval_baseline.json
```

Container / deploy: `docker build .` then `./start.sh` runs API (8000) + Streamlit (8501) together. `scripts/smoke_test.sh <url>` hits `/healthz` and `/ask`.

Tests:

```bash
.venv/bin/pytest tests/unit                      # backend unit tests (no DB/model needed; fakes)
cd web && npm run test:e2e                       # builds, then Playwright e2e against a fake FastAPI
cd web && npm run test:e2e:only                  # skip the build if .next is current
```

`tests/unit/test_resilience_backend.py` covers approve ownership / double-approve, the per-user in-flight cap, the per-conversation claim (409, release on failure, stale takeover), request bounds, history/transcript seeding and cache keys. `test_context_builder.py` covers the window/compaction rules — above all that no budget ever orphans a `tool_call_id`. `test_conversation_routes.py` covers `/conversations` and its 404-not-403 ownership rule. `test_memory_routes.py` and `test_episode_routes.py` cover the per-user `/memory` and `/episodes` (chat history) endpoints with fakes. `web/tests/e2e/` runs the production build with a real NextAuth JWT cookie against `tests/e2e/fake-backend.mjs`, a stand-in FastAPI that can be told to fail (question prefixes `APPROVAL`, `ASK`, `DROP`, `ERROR`, `SLOW`, `E500`…; `POST /__control {down:true}`). Needs Playwright's Chromium (`npx playwright install chromium`). `.github/workflows/ci.yml` only lints (non-blocking) and does an import check.

## Architecture

### The agent loop

`src/harness/agent/loop.py` is the core; everything else feeds it. `run_agent()` is a plain async while-loop over provider turns — **not** LangGraph (`agent/graph.py`, `nodes.py`, `state.py` are empty stubs). Each iteration:

1. Loads/creates a `Checkpoint` from `CheckpointStore` keyed by `thread_id` (which is the `run_id` — the checkpoint is still per **run**; the *conversation* is a separate table, see below). On a fresh run the caller may pass `initial_messages` (built from the conversation transcript) instead of `history`.
2. Calls `provider.chat_stream()` if an `on_event` callback was supplied and the provider supports it, else `provider.chat()`. Every turn is streamed, not just the last, because the text before tool calls is the agent narrating.
3. No tool calls → done. Otherwise appends the assistant message and dispatches each call through `guarded_dispatch`.
4. Saves the checkpoint after each step. Idempotency: `completed_calls` is keyed by `call_key(thread_id, name, args)`, so a resumed run replays a cached result instead of re-executing.

### Human-in-the-loop approval

`ToolPolicy` (`policy/`) maps tool name → `Tier`; `SAFE`/`SENSITIVE` → allow, `DESTRUCTIVE`/`ELICIT` → `NEEDS_APPROVAL`, else deny. The tier table lives in `api/routes/ask.py` (`_policy`).

When the loop hits a call needing approval it does **not** abort mid-message: calls before it run for real, the pending one gets an `[awaiting human approval]` placeholder tool message, later ones get `[not executed]`, and the checkpoint is saved with `status="pending_approval"` and `pending_tool`. This keeps the OpenAI message history valid (every `tool_call` has a matching `tool` reply). `POST /approve` (`routes/approve.py`) then overwrites that placeholder with the real result and calls `run_agent` again on the same `thread_id`.

`ask_user` is the same machinery used for clarification: its handler never really runs — it is tiered `ELICIT` purely so the loop pauses and the UI can render clickable options.

### Conversations (server-owned context)

A **conversation** is the durable chat; a **run** is one question→answer. They are different tables and it matters:

- `conversations` — id (`uuid4().hex`), `user_id` (the JWT `sub` string, like `threads.user_id`, *unlike* `episodes.user_id` which is `users.id`), title, the model/effort/connectors/mode/docs_only the chat was started with, the rolling compaction (`summary_text` + `summary_through_seq`), `next_seq`, conversation-wide `security` taint, and the claim (`active_run_id`, `active_run_started_at`). Hidden not deleted (`active`).
- `conversation_messages` — append-only, one row per message in **OpenAI wire shape**. `role` covers user/assistant/tool and `extra` carries `tool_calls`/`tool_call_id`/`ui`, so a later turn still sees what an earlier turn retrieved. Unique on `(conversation_id, seq)`; `seq` is allocated from `conversations.next_seq` under `SELECT … FOR UPDATE`.
- `threads` stays the per-run checkpoint, now with `conversation_id` and `persisted_upto` — the index past which `message` is not yet in the transcript, so `/approve` appends exactly the remainder of a resumed turn and appending twice is a no-op.

Note the table is `conversations`, **not** `sessions`: `sessions` is the Auth.js adapter table (`db/models.py`), and `data/sessions/<user_id>` is the per-user file sandbox. Avoid "session" in new backend identifiers.

`AskRequest.conversation_id` selects the chat (unknown or another user's → **404**, indistinguishable on purpose); absent means "start one", and the id comes back on `AskResponse.conversation_id` and the SSE `done`/`approval_required` events. Unset `model`/`effort`/`connectors`/`mode`/`docs_only` fall back to the conversation's stored values, which is what makes a resumed chat behave the same elsewhere. `AskRequest.history` is **deprecated**: ignored when a `conversation_id` is present, kept only for stateless callers (`streamlit_app.py`).

`agent/context.py` builds the seed. **The trap**: an assistant message carrying `tool_calls` and its `tool` replies are indivisible — an orphan `tool_call_id` is a provider 400 — so the window boundary is snapped back to a `user` message, never "the last N messages". `ctx.validate()` is called before the first turn and falls back to a history-less seed rather than failing the run. Older turns leaving the window are folded **once** into `conversations.summary_text` (keyed by `summary_through_seq`, so the summarising call happens only when the window advances); a failed summary drops the turns and logs.

`api/conversation_lock.py::conversation_slot` keeps a conversation to **one run at a time** (a second is `409` with `X-Reason: conversation_busy`), because two runs appending to one message list corrupt the *next* turn. It is a conditional `UPDATE … WHERE active_run_id IS NULL OR active_run_started_at < now() - CLAIM_TTL_S`, not an advisory lock: no pinned connection, and a replica killed mid-run leaves a claim that can be taken over after the TTL. It composes with `concurrency.run_slot` (per user), and `/approve` takes it too.

The transcript write is **awaited, not backgrounded** (`_persist_turn` in `ask.py`): it is correctness, and a background append that loses the race with the next turn silently drops a turn. The ledger and answer-cache writes stay backgrounded.

Two consequences worth knowing:
- **The canary is conversation-scoped.** `security.run_for(security_scope or thread_id)` is passed the conversation id, so replayed messages carry a canary `guard_output` still strips — a run-scoped one would leave stale canaries in the context. Taint is seeded from `conversations.security` into the fresh checkpoint and written back after the run, so a chat that ingested a poisoned document keeps its step-up on later turns.
- **The answer cache only serves a first turn.** Past that the answer depends on the transcript, which the key does not hash, so `/ask` skips the read when a `conversation_id` is given and `_finish_run` skips the write unless the conversation was empty.

`GET/POST /conversations`, `GET/PATCH/DELETE /conversations/{id}` are the API (mirrored at `web/app/api/conversations/*`); the rail (`ChatsPanel`) reads them and its rows open `/chat?c=<id>`. `episodes` is no longer the conversation record — it keeps only the embedding behind `recall_episodes`, keyed by `conversation_id` with a real title, written once per conversation by `_finish_run` (it used to be written by both the client and the server under different ids, producing a titleless duplicate row per answer).

### Per-user isolation (the closure pattern)

Auth is a JWT bearer token (`api/auth.py`); `user_id` is the `sub` claim. Isolation is structural rather than prompt-based, built by wrapping tools per request:

- `make_search_docs_tool(user_id)` — one pgvector query over `document_chunks` filtered to that user's rows, falling back to the shared corpus (`user_id IS NULL`). The isolation is the WHERE clause, so it holds across replicas and restarts.
- `wrap_filesystem_tool(tool, user_id)` — rewrites every path-bearing argument to `data/sessions/<user_id>/<basename>`, so the agent cannot escape its folder no matter what path the model invents. `/approve` re-applies the same forcing before executing an approved write.

A fresh `ToolRegistry` is built per request in `_build_and_run`; the module-level `_registry` in `ask.py` only holds the raw MCP-discovered tools that get wrapped.

Model and effort are per request: `AskRequest.model`/`effort` are validated by `providers/registry.py::resolve()` (422 otherwise), bound via `provider_for()` (a per-request `OpenAIProvider.bound()` sharing the cached client, which sends `reasoning_effort`), and effort also sets the loop's `max_steps`/`max_tokens` through `budget_for()`. Both are stamped on the checkpoint (`threads.model`/`effort`) so `/approve` resumes with the same settings, and both are in the cache key. `GET /models` serves the registry to the UI (`components/hangul/ModelPicker`).

`docs_only=True` swaps in a restricted registry (search_docs only) plus `DOCS_ONLY_INSTRUCTION`, and passes `force_tool_use` so the first turn uses `tool_choice="required"`.

### Streaming path

`POST /ask/stream` (`routes/ask_stream.py`) runs the agent as a background task pushing events onto an `asyncio.Queue`, and drains it as SSE (`step`, `text_start`/`text_delta`/`text_end`, `tool_pending`, `tool_args_delta`, `tool_call`, `tool_result`, `approval_required`, `done`). `tool_pending`/`tool_args_delta` come from the provider's `chat_stream` (`("tool_start", …)`, `("tool_args", …)`) the moment the model names a tool and as it generates the JSON arguments, so the UI can show a file's content being drafted before the call is complete. `web/app/api/chat/route.ts` is a BFF that authenticates the NextAuth session, mints a short-lived service JWT with `FASTAPI_JWT_SECRET`, forwards to FastAPI, and translates those events into AI SDK UI-message parts (`data-tool` parts reuse the tool-call id so a result replaces its own running card; `data-status` id `status` is the thinking indicator; a `tool_result` whose preview says "awaiting approval" becomes status `awaiting`, never `done`). Changing an event name means changing it in all three places: `loop.py` emit → `ask_stream.py` → `route.ts`.

`POST /ask` is the non-streaming equivalent and is the only path with the Redis answer cache; the cache key (`cache/keys.py`) hashes question + prompt version + model + tool names + user id, so anything that can change the answer must be in it.

### MCP

Servers are declared in `src/harness/mcp/servers.yaml` (`load_server_configs()` in `mcp/config.py`; missing/empty file falls back to the filesystem server). Each entry picks a transport — `stdio` (command/args/env/cwd), `streamable_http` or `sse` (url/headers) — and `${VAR}` in values is expanded from the environment. Currently only `@modelcontextprotocol/server-filesystem` over stdio scoped to `docs` and `data/sessions`. Node/npx must be available — the Dockerfile installs it for this reason.

`MCPManager` (`mcp/manager.py`) owns one `MCPClient` per server: `connect_all()` fans out in parallel and isolates failures (a dead server is logged and marked `failed`, the API still boots); `discover()` lists and adapts tools; every tool is exposed as `<server>__<tool>` (`qualify`/`split`); `register_into(registry)` pushes them into `ask.py`'s `_registry`; `call_tool(qualified, args)` routes to the right client, reconnects a `failed` server once (per-server lock) before the call, and returns errors as text (`[mcp error] …` for transport problems, `[tool error] …` when the server sets `is_error`) instead of raising; `aclose()` tears everything down even if a client fails. Tool handlers call back into the manager, never a raw client. `GET /healthz` includes per-server `{state, tool_count, last_error}` via `mcp.manager.current()`.

`MCPClient` runs each connection in its own owner task because the SDK's transport/session context managers use anyio cancel scopes that must be entered and exited by the same task — do not enter them directly from a `gather`-ed coroutine. `supervisor.py` and `schema_snapshot.py` are still empty placeholders.

### Token vault (`src/harness/vault/`)

Third-party credentials never reach the model, a tool handler, or an MCP server process. `Vault` (`vault/vault.py`, process-wide via `vault.current()`, built in the lifespan by `vault/bootstrap.py`) stores secrets Fernet-encrypted (`VAULT_MASTER_KEY`; unset = vault disabled and `web_search`/`vault_*` report `VAULT_UNAVAILABLE`), mints short-lived **grants** (`vg_…` opaque tokens; only the SHA-256 is kept, in Redis with the TTL), and proxies every outbound call (`vault/proxy.py`) — the only place a credential is decrypted. `providers.py` is the fixed allowlist of hosts and injection styles (`tavily`, `github`, and `http:<host>` for a user-supplied base URL); a grant carries `access=read|write`, and the spec decides what counts as a write (Tavily's `POST /search` is a read). Policy (`policy.py`) checks host/method/path/body size/call budget before decrypting.

- **Ownership**: `user_id NULL` = operator (system) credential. `TAVILY_API_KEY` from `.env` is auto-imported as one at startup, and `tavily` is in `AUTO_CONSENT_PROVIDERS`, so `web_search` works with no UI step. Everything else needs a consent row.
- **Consent**: `vault_consents` — standing, per provider, with a TTL; `allow_write` only makes writes *eligible*. The agent tools are `vault_request` (GET only, tier `SENSITIVE`) and `vault_mutate` (POST/PUT/PATCH/DELETE, tier `DESTRUCTIVE`, so each call pauses for `/approve`). Both are built per request by `build_vault_tools(user_id, thread_id)` (`tools/builtin/vault_request.py`) and their descriptions list the providers the user has consented to. A missing consent comes back as `VAULT_CONSENT_REQUIRED: … /vault` text, never an elicitation.
- **MCP**: in `servers.yaml`, `"vault:<provider>"` becomes a fresh grant at every connect (revoked on close) and `"vault-proxy:<provider>"` becomes `<vault_public_url>/vault/proxy/<provider>/`, so a stock server with a base-URL override never holds the real token. A raw `${SECRET}` in a secret-looking key logs a warning.
- **Redaction**: `vault/redact.py` holds every credential decrypted and grant minted in this process; `AuditLog`, the loop's `completed_calls`/`tool_result` preview, and trace span attributes are all scrubbed through it. Anything else that persists tool output must call `redactor.scrub_text` too.
- **Routes**: `/vault/{providers,credentials,consents,audit}` are JWT-guarded and never return ciphertext; `POST /vault/proxy` and `ANY /vault/proxy/{provider}/{path}` are authenticated by the grant alone. The BFF mirrors them under `web/app/api/vault/*` (`_shared.ts`) and `web/app/vault` is the management page (linked from `ProfileMenu`).

### Connectors (`src/harness/connectors/`)

Optional tool sources the user switches on **per conversation** from the composer's `+ → Connectors` submenu (hover or click), mirroring how Claude.ai does it. The selection is per tab (`sessionStorage` `hangul:connectors`, shared by the landing page and `/chat`, saved with the thread) and goes up as `AskRequest.connectors` (validated → 422). `add_connector_tools()` in `ask.py` adds the connector's tools to the session registry and its paragraph to the system prompt; the keys are stamped on `threads.connectors` so `/approve` resumes with the same tools. `GET /connectors` (public) is the catalogue.

- Kinds: **builtin** (`registry.BUILTIN`; tools are a factory, tiers declared) and **mcp** (a `servers.yaml` server tagged `connector` — its `<server>__*` tools are only exposed when on). Servers sharing a `bundle:<key>` tag become **one** connector; a `per-user` server (headers with `user-token:<source>`) is never connected at boot — `MCPManager.ensure_user_session(server, user_id)` opens the user's own session (`connectors.registry.prepare()` does this before a run; idle sessions are reaped after 30 min) and `tools_for_subject` binds the tools to it.
- **Google Workspace connector** (`google`, builtin, per-user): `connectors/google_rest.py` — Gmail (`search_messages`, `get_thread`, `get_message`, `create_draft`, `send_message`, `send_draft`), Calendar (`list_events`, `create_event`), Drive (`search_files`, `get_file`), Docs (`get_document`, `append_text`) over Google's REST APIs with the user's token from `integrations/google_oauth.py`. Tools return `ToolOutput(text, ui)`: the text is what the model reads; `ui` (a `kind` + data) rides on the `tool_result` event → `data-tool.ui` → `components/hangul/GoogleCards.tsx` renders Gmail/Calendar/Drive/Docs-styled cards (`.g-*` tokens in `globals.css`), and the approval card shows a Gmail compose preview for sends/drafts. Any handler may return `ToolOutput`; `dispatch()` unwraps it. Google's official MCP servers are still declared below but need a Workspace org in the Developer Preview.
- **Google Workspace MCP bundle** (disabled): Google's official MCP servers (`gmailmcp/calendarmcp/drivemcp/docsmcp.googleapis.com`, streamable HTTP) declared in `servers.yaml` with `Authorization: Bearer user-token:google:<product>`. `integrations/google_oauth.py` turns the refresh token Auth.js stored on the user's `accounts` row (granted when they click *Connect Google Workspace* at `/vault`, which re-runs Google sign-in with the Workspace scopes + `access_type=offline`; `web/auth.ts` persists the new tokens) into a cached access token using `auth_google_id/secret`. `GET /integrations` reports connection + products; `DELETE /integrations/google` forgets the token and closes sessions. Policy: `_policy` **patterns** (`ToolPolicy(patterns=...)`) make `gmail__*send*`, `calendar__*create*`, `drive__*delete*`… DESTRUCTIVE (approval) and the rest of `gmail__*/calendar__*/drive__*/docs__*` SENSITIVE.
- `arxiv` = the **Research** connector: `arxiv_search` / `arxiv_paper` over the public Atom API in `connectors/arxiv.py`, deliberately built in rather than a subprocess (no credential, one GET, the 3-second courtesy rate limit is enforced in-process, nothing written to disk). Bare queries get `all:`; fielded syntax (`ti:`, `au:`, `cat:`…) passes through.
- Evals: `EvalCase.connectors` switches them on per case; concern `research` allows `arxiv_*` (+ `search_docs`). `run_evals.py --ids ts15,ts16` runs just those.

### Prompt-injection defence (`src/harness/security/`)

Layered, in the order a request meets them; `SecurityGuard` (`guard.py`, process-wide via `get_guard()`, built in the lifespan) is called by the loop at each seam and every layer raises a `SecurityEvent` that is streamed to the UI (`security` event → `data-security` part → a notice card), returned as `security_events`, audited (`kind: security`), and summarised on `/admin` (`/admin/security`).

1. **Hardened prompt** — static trust-boundary rules in `system_agent.txt` plus a per-thread block (`guard.harden`) naming the boundary tag and a **canary** token. Canary/boundary are an HMAC of the thread id, so `/approve` resumes match the checkpointed prompt without storing them.
2. **Input screen** — `detector.scan()` on the user's message: normalises (NFKC, strips zero-width/bidi/tag chars), scores pattern families (override, role hijack, addressed-to-assistant, exfiltration, tool coercion, covert, hidden text, base64-decoded payloads). Flagged → event; more than `security_offender_limit` in the window → `/ask` answers 429 (`X-Reason: security_throttled`).
3. **Spotlighting** — every tool result reaches the model as JSON `{tool, source, trust:"untrusted", content}` inside `<tr-…>` boundaries with a reminder (`spotlight.py`); the raw text still goes to `completed_calls`/`retrieved_context`.
4. **Tool-result screen** — the same detector (+ optional LLM classifier, `security_llm_screen`) on every result; a hit adds a `warning` to the spotlighted JSON and **taints** the run (`threads.security`).
5. **Action guard** — `output.scan_arguments` refuses outright any call whose arguments carry a vault secret/grant or the canary (`Blocked by security policy…` goes back to the model); an encoded blob or oversized outbound argument, or *any consequential call once the run is tainted* (`guard.is_consequential`: web/vault/arxiv/remember/file writes), becomes a `pending_approval` — the existing HITL flow.
6. **Output guard** — `output.guard_output`: vault redaction, canary removal, external markdown images replaced, URLs with long encoded params defanged. On the streaming path the raw text was already sent, so the `output` event carries the guarded `answer` and the chat page renders it instead of the streamed text.
7. **Oversight** — uploads are scanned at ingest (`/upload` returns `security.warning`), the admin page counts events by layer/severity/action, and the `prompt_injection` eval suite (`data/evalsets/prompt_injection.jsonl`, `eval/security_graders.py`) poisons one tool's result per case and reports attack-success, leak, detection, task-completion and (judge) reported rates.

Adding a tool that can move data out of the system: put it in `guard.OUTBOUND` (step-up on taint) and, if it takes free text, in the outbound set in `output.scan_arguments`.

### Personal-assistant features

- **Personalisation** — `user_settings` (`db/settings.py`): display name, tone (concise/balanced/detailed), timezone, language, custom instructions (≤2000 chars). `prompt_block()` is appended to every system prompt as `=== ABOUT THE USER ===` (with local time), ranked like user messages: honoured unless they conflict with the rules above. Part of the answer-cache key (`prefs_version`). `GET/PUT /settings`; page `/settings` (Profile menu → *Personalisation & tasks*).
- **Scheduled tasks** — `scheduled_tasks` (`db/tasks.py`): a question + `every_minutes` (≥15) or `daily_at` HH:MM in the user's timezone, with connectors and mode. `scheduler.py` polls every minute inside the API lifespan (`scheduler_enabled`), runs due tasks through `_build_and_run` (same tools, security, ledger), stores `last_status/last_answer`, and writes an episode titled `⏰ <title>` so it shows in the Chats rail. A task that pauses for approval is `needs_approval`. `/tasks` CRUD, `/tasks/{id}/run` (now), `/tasks/{id}/enabled`. Not replica-safe yet: every replica with the scheduler on would run due tasks.
- **Deep research mode** — `AskRequest.mode="research"`: appends `RESEARCH_INSTRUCTION` (plan → several searches across docs/web/arXiv → reconcile → numbered citations + Sources list), doubles the step/token budget, and auto-enables the `arxiv` connector. Chip *Deep research* in the chat composer; in the cache key.
- `OpenAIProvider._create` retries once **without** `reasoning_effort` when OpenAI rejects it alongside function tools on `/v1/chat/completions` (gpt-5.5 does today); the real fix is the Responses API.

### Prompts, evals, observability

- Prompts are files in `prompts/templates/*.txt`; `get_prompt()` versions them by SHA-256 prefix, so editing the text changes `prompt_version` and busts the cache. Prompt version is recorded on every run and every eval report.
- Evals live in `src/harness/eval/` (the top-level `evals/` directory is empty stubs). Two suites (`catalog.py::SUITES`), both run by `eval/agent_runner.py::run_suite` (shared by `run_evals.py` and the admin API, and it brings up MCP + the vault itself when run from the CLI):
  - `qa`: `data/evalset.jsonl` → `run_eval` → LLM judge scores correctness and faithfulness. `evaluate_gate` blocks on floors of 0.80 and on regressions >0.05 vs `data/eval_baseline.json`. `GET /quality` surfaces the newest report plus the gate verdict.
  - `tool_selection`: `data/evalsets/tool_selection.jsonl` — each case says which **concern** the request is about and which tools are expected / tolerated / forbidden, expected arguments, whether it must pause for approval, and what the answer must not claim. The run is captured as a `Trajectory` (`eval/trajectory.py`, from the loop's `on_event` stream plus full tool outputs from the checkpoint) and graded by `eval/tool_graders.py`: tool_choice (set-F1), tool_necessity (unneeded/repeated/forbidden calls), hallucination (invented tools/args deterministically, plus a judge on "claims an action no call backs"), separation_of_concerns (`CONCERN_TOOLS`), argument_correctness, approval_compliance, and efficiency/cost numbers. A case passes when every dimension ≥ 0.7.
  - Reports are `data/eval_runs/<suite>-<stamp>.json` (`eval-*` = qa) read by `eval/store.py`. `eval/catalog.py::CATALOG` lists every eval with `status` available/planned; add a new eval there and in a suite.
- Admin console: `routes/admin.py` (`/admin/whoami`, `/admin/evals/{catalog,summary,runs,run,status}`, `/admin/overview`) sits behind `auth.require_admin`, which needs **all** of: an email in `settings.admin_emails` (hard-coded default in `config.py`, comma-separated env override), `auth_provider == "google"`, `auth_at` within `admin_max_auth_age_s` (12h), and — if `admin_ip_allowlist` is set — a direct peer IP in it (`X-Forwarded-For` is deliberately ignored; terminate the allowlist at the proxy). The `role` claim alone never grants admin. Every accepted call is an `{"kind": "admin"}` row in `data/audit.jsonl`; denials are logged with the reason.
  The web tier: `web/auth.ts`'s `jwt` callback records `provider` and `authAt` on the sign-in request; `lib/bff.ts::requireAdmin` only checks "Google-backed and recent" and answers `401 unauthorized` / `401 reauth_required` — it never sees the allowlist; `upstream(..., {identity})` mints the 5-minute service token with `email`/`auth_provider`/`auth_at` claims; `app/api/admin/_shared.ts` adds same-origin on mutations, a rate limit, `no-store` + `noindex` headers, and relays the backend's 403 as `forbidden`. `next.config.ts` adds HSTS globally and `no-store`/`noindex`/`no-referrer` on `/admin*`. The page (`web/app/admin`, linked from the settings gear on every page) renders one of: Google-only sign-in card, re-auth card, "not an administrator" card, or the console — driven by `/api/admin/whoami`. e2e: `signInAs(ctx, operator, url)` (`operator@example.com` is the fake backend's allowlist), `{provider: "resend"}` / `{authAt}` for the denial paths.

## Conventions and traps

- `ToolRegistry.registry(tool)` is the *add* method (not a property), and `Tool.parameter` is singular. Both read like typos; they are the API.
- `Checkpoint.message` (singular) is the full message list.
- Config is pydantic-settings reading root `.env`; field names are lowercase (`openai_api_key`, `database_url`). `get_settings()` is *not* cached, but `get_provider()` and `get_embedder()` are — changing `.env` at runtime won't reach them.
- Retrieval vectors live in Postgres (`document_chunks`, HNSW + `vector_cosine_ops`), reached through `retrieval/pg_store.py`; the SQLAlchemy engine is sync, so the async helpers there hand the query to a thread. `retrieval/store.py` (the `data/index.json` `VectorStore`) is now only the `--backend json` ingest path. `docker-compose.yml` runs `pgvector/pgvector:pg16` because the stock image has no `vector` extension.
- `web/` is Next.js 16: middleware is `web/proxy.ts`, not `middleware.ts`. Follow `web/AGENTS.md` and read `node_modules/next/dist/docs/` before writing Next-specific code.
- Frontend theme: every page uses `components/hangul/AppHeader` (+ `SignInModal` if it needs a session) and the `.h-*` classes / `var(--fg|--muted|--surface|--solid-bg…)` tokens from `globals.css`. Tailwind's shadcn tokens are mapped to the same palette. Never hard-code colours. See `docs/notes/2026-09-15-frontend-theme-unification.md`.
- BFF routes (`web/app/api/*`) all go through `web/lib/bff.ts`: same-origin check → session → per-user rate limit → `upstream()` with a timeout; errors are `{detail, code}`. Add new routes the same way. The backend caps runs per user (`api/concurrency.py`) and `threads.user_id` is checked on `/approve` (`CheckpointStore.claim_pending`).
- The **server** owns the chat transcript (`conversations` / `conversation_messages`). `sessionStorage` (`hangul:chat:<user id>:<conversation id>`, plus `hangul:chat:active:<user id>` naming the tab's current chat) is only an optimistic cache: the page paints from it instantly and then reconciles against `GET /api/conversations/<id>`. So a chat reopens in a tab that never showed it, and on another device. Every completed run ends with a hidden `data-run` part (used by tests as the end-of-run marker; not shown to the user) carrying `conversationId`.
- Never read `settings.tavily_api_key` (or any third-party key) inside a tool; go through `vault.current().call(...)`. `tavily-python` was removed for this reason.
- `streamlit_app.py` still authenticates with an `X-Session-ID` header, which the JWT-guarded routes no longer accept; treat it as legacy unless you are updating it.
