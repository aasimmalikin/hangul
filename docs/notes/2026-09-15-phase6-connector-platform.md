# Phase 6 — Connector platform: requirements & decision log

Started 2026-09-15. This is a living document: the top half is the audit of what
exists vs. what each step needs; the bottom half (`## Decision log`) is appended
to as work happens. Nothing here is implemented yet unless the log says so.

Scope (steps 29–40): provider registry, MCP client manager, token vault, context
compaction, arXiv, YouTube + Google Maps, Postgres, Google bundle (Calendar,
Gmail read/send), Slack, Discord, injection defense + red teaming, tool-selection
eval.

---

## 0. What the codebase gives us today (audit)

Read before planning; these are the load-bearing facts.

| Area | State | Consequence for Phase 6 |
|---|---|---|
| `providers/base.py` | `Provider` Protocol declares only `chat()`. `loop.py` also uses `.model`, `chat_stream()`, `tool_choice=`. | Protocol is a lie; must be widened before a second provider can exist. |
| `providers/__init__.py` | `get_provider()` is `@lru_cache`, hard-wires `OpenAIProvider`. | Registry has to replace this, and cache-busting/config-reload becomes explicit. |
| `obs/tracing.py` | `PRICING = {"gpt-5.5": ...}` keyed by model id, else cost = 0. | Every new model id needs a pricing row, or the ledger silently under-bills. |
| `mcp/manager.py`, `client.py` | stdio only; servers hard-coded in `api/app.py` lifespan; tools registered into one global `_registry` at startup; no reconnect; `servers.yaml`, `supervisor.py`, `schema_snapshot.py` empty. `_owner[namespaced] = None` so the shadowing alert prints `None`. | Fine for filesystem. Not usable for per-user, credentialed connectors (a Gmail server started at boot has no user's token). |
| Tools | `Tool(name, description, parameter, handler)`; per-user isolation via closures (`make_search_docs_tool(user_id)`, `wrap_filesystem_tool`). | Connectors follow the same closure pattern: `make_gmail_tools(user_id)` looks up the vault at call time. |
| Policy | `ToolPolicy` is a flat `name → Tier` dict in `routes/ask.py`; unknown → `SENSITIVE` → allowed. | Default-allow is wrong once outbound tools exist. Must flip to default `DENIED` for unknown names and enumerate every connector tool. |
| Budget | `Budget.max_tokens=50_000` is **cumulative** across turns, checked at top of each step. | Compaction shrinks the *prompt*, not the cumulative counter. Need to separate "context window guard" from "spend cap". |
| Checkpoint | `Checkpoint.message` is the raw OpenAI message list; `/approve` finds the placeholder by `tool_call_id`; `completed_calls` keyed by `call_key(thread, name, args)`. | Compaction must never drop the `[awaiting human approval]` tool message nor split an assistant `tool_calls` message from its `tool` replies. |
| Episodes (step 16) | `_summarize_thread()` in `ask.py` is an f-string (`"User asked X. Assistant answered: Y[:400]"`), not an LLM summary. | The "episodic-summarization primitive" compaction is meant to reuse **does not exist yet**. Build it once, use it twice. |
| Auth | NextAuth (Google + Resend) → JWT `sub` = `users.id`. `accounts` table already stores Google `refresh_token`/`access_token` **in plaintext**, scope = sign-in only. | Gmail/Calendar need extra scopes via a separate "Connect Google" consent flow, not sign-in. The vault should own those tokens, encrypted, distinct from the NextAuth row. |
| Eval | `run_fn` returns `(answer, context)`; `EvalCase` has `id, question, reference`; graders: correctness + faithfulness. `AgentResult.tools_used` already exists. | Tool-selection eval = add `expected_tools` to cases + plumb `tools_used` out of `run_fn`. |
| `tools/cassette.py` | Exists (record/replay of tool calls). | Reuse for red-team and tool-selection evals so they don't hit real Gmail/Slack. |
| Tests | `tests/` empty. | Each step below ships with unit tests; connectors get a cassette-backed integration test. |

---

## 1. Per-step requirements

Format: **Needs from you** (accounts, keys, decisions) / **Needs in code** / **Tier** / **Open questions**.

### 29. Provider registry (GPT-6 Astra)

**Needs from you**
- The exact model id string for GPT-6 Astra and which API it is served through (OpenAI Chat Completions? Responses API? A different vendor base URL?). I do not have this in my knowledge; I will not guess it.
- Its per-million input/output price, for `PRICING`.
- Whether Anthropic models should be registered in the same pass (would add `anthropic` dependency and a second `Provider` impl).

**Needs in code**
- `providers/base.py`: widen `Provider` Protocol to `model: str`, `chat(..., tool_choice=)`, `chat_stream(...)`. Make `chat_stream` optional via `supports_streaming` flag rather than `hasattr`.
- `providers/registry.py`: `PROVIDERS: dict[str, factory]`; `settings.provider` (`openai` default) + `settings.model`; `get_provider(name=None)` keyed cache so per-request overrides (evals on a different model) are possible.
- `OpenAIProvider`: accept `base_url` so an OpenAI-compatible endpoint (which is what "Astra" is most likely to be) is config, not code.
- `obs/tracing.py`: pricing row per registered model; fail loudly in dev (`log.warning`) when a model has no pricing.
- Answer cache key already includes `model` — no change.

### 30. MCP client manager

**Needs from you**
- Decision: which connectors are MCP-backed vs native Python. **Recommendation:** all Phase 6 connectors are **native** (see D-2 below); the MCP manager upgrade is for *user-supplied remote MCP servers* and future third-party ones, not for Gmail/Slack.

**Needs in code**
- Fill `mcp/servers.yaml` (name, transport, command/url, allowed_tools, tier defaults) and load it in lifespan instead of the hard-coded list.
- Add Streamable-HTTP transport alongside stdio (`mcp` SDK already supports it). Per-server auth header from the vault or env.
- `supervisor.py`: restart-on-crash with backoff, health ping, and mark tools unavailable (not missing) while a server is down so the model gets a clear error instead of `unknown tool`.
- `schema_snapshot.py`: persist `list_tools()` output per server to `data/mcp_snapshots/<server>.json`; diff on startup and alert on schema drift (a changed tool description is a prompt-injection vector — see step 39).
- Fix `_owner[namespaced] = name` so the shadowing alert is meaningful.

### 31. Token vault

**Needs from you**
- A 32-byte key for encryption at rest → `VAULT_KEY` in `.env` (I'll generate one with `Fernet.generate_key()` and tell you where to put it; you keep it out of git).
- Decision: KMS/HSM later, or is env-key Fernet acceptable for now? (Assumed: yes for now.)

**Needs in code**
- New table `connector_credentials` (alembic migration): `user_id, provider ('google'|'slack'|'discord'|'postgres'), scopes, ciphertext (refresh token / API key / DSN), access_token_cache, expires_at, created_at, revoked_at`. Unique on `(user_id, provider)`.
- `harness/vault/`: `put/get/revoke`, Fernet via `cryptography` (new dep), refresh-on-expiry hook per provider, never logs secrets (structlog processor that redacts keys named `token|secret|password|dsn`).
- Routes: `GET /connectors` (status per provider), `POST /connectors/<provider>/authorize` (start OAuth), `GET /connectors/<provider>/callback`, `DELETE /connectors/<provider>`.
- Web: `web/app/connectors/page.tsx` — connect/disconnect cards using the existing `AppHeader` + `.h-*` theme tokens. BFF routes mint the same service JWT as `api/chat/route.ts`.
- The NextAuth `accounts` row keeps its sign-in-scope tokens; the vault stores the *connector-scope* grant separately so revoking Gmail never logs the user out.

### 32. Context compaction

**Needs from you**
- Threshold and tail size defaults. Proposed: compact when the last turn's `input_tokens` > 60 % of the model's context window; keep last **8 messages** verbatim (roughly 3 tool round-trips). Both are settings.
- Whether the raw pre-compaction messages must be retained for audit (proposed: yes, in a `compaction_log` JSONB column on `threads`, since the checkpoint table already holds the live messages).

**Needs in code**
- `harness/memory/summarize.py`: the missing step-16 primitive. `summarize_messages(messages, provider) -> str`, one LLM call, prompt template `prompts/templates/summarize_turns.txt` (so it is versioned like every other prompt). Replace the f-string `_summarize_thread` with it.
- `agent/compaction.py`: `compact(messages, keep_last=N) -> messages`. Rules:
  1. Message[0] (system) is never touched.
  2. Cut point is moved backwards until it lands *after* a complete assistant→tool group, so no `tool_call_id` is orphaned.
  3. Any `tool` message whose content is `[awaiting human approval]` or `[not executed …]` is inside the verbatim tail by construction (it is always in the most recent group), but assert it anyway.
  4. Synopsis is inserted as a single `{"role":"user","content":"[Context synopsis of earlier turns]\n…"}` right after the system message. `user` role, not `system`, so providers that allow one system message stay happy.
  5. Repeat compactions fold the previous synopsis into the new one.
- `loop.py`: measure with `turn.input_tokens` of the *previous* turn (free — it's already reported) rather than adding `tiktoken`. Check before each `provider.chat*`. Emit a `compaction` SSE event so the UI can show "condensed N earlier turns" (→ `ask_stream.py` → `route.ts`, same three-place rule as every event).
- `Budget`: split into `max_context_tokens` (per-turn, triggers compaction) and `max_total_tokens` (cumulative spend cap, raised for connector runs). Compaction cost is counted toward the spend cap.
- `completed_calls` is untouched — idempotent replay keeps working after compaction.

### 33. arXiv

**Needs from you:** nothing (public API, no key). Rate-limit etiquette: 1 req / 3 s.
**Needs in code:** `tools/builtin/arxiv.py` — `arxiv_search(query, max_results, sort)` and `arxiv_get(id)`, Atom API via `httpx` (new dep, replaces `requests` for async). Results formatted like `web_search` (`[title] (url)\nabstract`) so citation behaviour is consistent. Optional: `arxiv_fetch_pdf(id)` → pipe through existing `upload_ingest` so papers become searchable via `search_docs`.
**Tier:** SAFE.

### 34. YouTube, Google Maps

**Needs from you**
- A Google Cloud project (the one already used for the OAuth client is fine) with **YouTube Data API v3** and **Places API / Geocoding / Directions** enabled, and one API key restricted to those APIs → `GOOGLE_API_KEY`. Billing must be enabled on the project for Maps.
- Decision on transcripts: official Data API has no transcript endpoint; `youtube-transcript-api` scrapes and breaks periodically. Proposed: include it, wrap in the same "UNAVAILABLE, do not retry" error pattern as `web_search`.

**Needs in code**
- `tools/builtin/youtube.py`: `youtube_search`, `youtube_video_info`, `youtube_transcript`.
- `tools/builtin/maps.py`: `maps_geocode`, `maps_places_search`, `maps_directions`.
- These are service-key tools (not per-user) so they register like `WEB_SEARCH_TOOL`, not via closure.
**Tier:** SAFE (all read-only).

### 35. Postgres connector

**Needs from you**
- Which database(s) the agent may query, and a **read-only role** on each (I will give you the `CREATE ROLE … ; GRANT SELECT …` snippet). The harness's own DB is *not* exposed by default.
- Decision: one global DSN in settings, or per-user DSNs stored in the vault? Proposed: per-user via vault (`POST /connectors/postgres` with a DSN), so the closure pattern applies and one user's DSN is never visible to another.

**Needs in code**
- `tools/builtin/postgres.py` with `asyncpg` (already a dep): `pg_list_tables`, `pg_describe(table)`, `pg_query(sql)`.
- Guards on `pg_query`: single statement, must parse as `SELECT`/`WITH` (use `sqlglot` or a strict regex + `EXPLAIN` dry-run), `SET statement_timeout = 5000`, `SET default_transaction_read_only = on`, hard `LIMIT 200` appended if absent, result truncated to N KB with a "truncated" marker.
- Not using `@modelcontextprotocol/server-postgres` (archived upstream; no per-user credential story).
**Tier:** `pg_query` SENSITIVE (allowed, audited). No write tool ships in this phase.

### 36. Google bundle — Calendar, Gmail read/send

**Needs from you**
- In the existing Google Cloud OAuth client: enable **Gmail API** and **Google Calendar API**; add redirect URI for the connector callback; add scopes `gmail.readonly`, `gmail.send`, `calendar.readonly`, `calendar.events`.
- `gmail.send` and `gmail.readonly` are *restricted* scopes: unverified apps are limited to 100 test users and show a warning screen. Decide: stay in testing mode with listed test users (fine for now), or start Google's verification (weeks, needs privacy policy + demo video).
- Confirm the approval UX: every `gmail_send` and `calendar_create_event` pauses for approval (existing HITL), and the approval card must show the **full** recipient/subject/body.

**Needs in code**
- OAuth incremental-consent flow through the vault routes (step 31). `google-auth` + `google-api-python-client` or raw REST via `httpx` — proposed raw REST to avoid the heavy client and keep everything async.
- `tools/builtin/google/gmail.py`: `gmail_search(query, max)`, `gmail_get(id)`, `gmail_send(to, subject, body, reply_to_id?)`. `gmail_get` returns text/plain part only, HTML stripped, attachments listed not fetched.
- `tools/builtin/google/calendar.py`: `calendar_list_events(start, end)`, `calendar_create_event(...)`.
- All built by `make_google_tools(user_id)`; if no vault entry, the tools are **not registered** for that request (the model shouldn't see tools it can't use).
**Tier:** reads SAFE-but-tainted (see 39); `gmail_send`, `calendar_create_event` DESTRUCTIVE.

### 37. Slack

**Needs from you**
- Create a Slack app; decide **bot token** (workspace-level, installed once by an admin) vs **user token** (per user via OAuth, acts as them). Proposed: OAuth v2 with user token stored in the vault so messages are sent *as the user* and permissions are theirs — consistent with the per-user isolation model. Scopes: `channels:history`, `channels:read`, `search:read`, `chat:write`, `users:read`.
- Client ID/secret → `.env`; redirect URI registered.

**Needs in code:** `tools/builtin/slack.py` — `slack_search`, `slack_read_channel`, `slack_post_message`. `slack_sdk` (async) or raw `httpx`.
**Tier:** reads SAFE-tainted; `slack_post_message` DESTRUCTIVE.

### 38. Discord

**Needs from you**
- A Discord application + **bot token** and the bot invited to the target server(s) with `Read Messages/View Channels`, `Read Message History`, `Send Messages`. Discord has no meaningful per-user OAuth for reading channels, so this one is **bot-level** (single token in the vault under a `system` user, or `.env`).
- Decision: which guild/channel IDs are allowed (an allowlist in settings, not "everything the bot can see").

**Needs in code:** `tools/builtin/discord.py` over REST only (no gateway/websocket — we don't need events): `discord_list_channels`, `discord_read_messages(channel, limit)`, `discord_send_message(channel, content)`.
**Tier:** reads SAFE-tainted; `discord_send_message` DESTRUCTIVE.

### 39. Injection defense + red teaming

This is the step that makes 33–38 safe to ship. Every read connector returns **untrusted text** (an email body, a Slack message, a YouTube description, a DB row) that lands in the model's context.

**Needs from you**
- Sign-off on the policy change: **once untrusted content has entered a run, every outbound tool (`gmail_send`, `slack_post_message`, `discord_send_message`, `filesystem__write_file`, `web_search`) requires approval**, even ones normally SAFE. (`web_search` is included because the query string is an exfiltration channel.)
- A budget for red-team eval runs (they call the real model; ~50 cases × steps).

**Needs in code**
- **Provenance wrapping**: every connector result is wrapped `<<untrusted source="gmail" id="…">> … <</untrusted>>` with a fixed instruction in `system_agent.txt` that content inside these markers is data, never instructions. Marker strings are escaped if they appear inside the payload.
- **Taint tracking in the loop**: `AgentResult`/checkpoint gets `tainted: bool`; `ToolPolicy.decide(name, tainted=)` escalates outbound tools to `NEEDS_APPROVAL` when tainted. `Tool` gets an `untrusted_output: bool` and `outbound: bool` flag so this is declared per tool, not in a name list.
- **Output scanner** (cheap heuristics first, classifier later): flag tool results containing "ignore previous instructions", role markers (`system:`, `assistant:`), base64 blobs, or URLs with query strings containing things that look like secrets; annotate rather than block, and surface in the audit log + a `warning` SSE event.
- **Argument screening on outbound calls**: reject/approve-with-warning if arguments contain content that appeared only in untrusted tool results (simple substring check over the last N tool outputs).
- **Schema drift alert** from step 30 (tool descriptions are part of the prompt).
- **Red-team suite**: `data/redteam.jsonl` — cases with a planted injection in a cassette-recorded tool result and an `expected: {no_outbound_call | approval_required}` assertion. `run_redteam.py` + `ci_gate.py` extension: any case that produces an unapproved outbound call is a hard fail. Uses `tools/cassette.py` so nothing real is sent.

### 40. Tool-selection eval

**Needs from you**
- 20–40 labelled questions with the tool(s) a good agent *should* call (and a few "should call nothing" cases). I'll draft them from the existing evalset + connector scenarios; you correct.
- Floors for the gate. Proposed: tool precision ≥ 0.80, recall ≥ 0.80, "forbidden tool called" = 0.

**Needs in code**
- `EvalCase` gains `expected_tools: list[str]`, `forbidden_tools: list[str]` (optional).
- `run_fn` returns a richer result (answer, context, tools_used) — `AgentResult` already has `tools_used`.
- `eval/graders.py`: `grade_tool_selection()` — set precision/recall per case, no LLM judge needed. Report gains `avg_tool_precision`, `avg_tool_recall`, `forbidden_calls`.
- `gate.py` + `data/eval_baseline.json` + `GET /quality` updated. Cassette playback so this eval is cheap and deterministic apart from the model call.

---

## 2. Cross-cutting requirements

- **Dependencies to add:** `httpx`, `cryptography`, `sqlglot` (or accept a regex guard), optionally `youtube-transcript-api`, `slack_sdk`. Not adding Google's client libraries.
- **`.env` additions:** `PROVIDER`, `MODEL`, `OPENAI_BASE_URL`, `VAULT_KEY`, `GOOGLE_API_KEY`, `GOOGLE_CLIENT_ID/SECRET` (backend copy for the connector OAuth), `SLACK_CLIENT_ID/SECRET`, `DISCORD_BOT_TOKEN`, `DISCORD_ALLOWED_CHANNELS`, `COMPACT_AT_TOKENS`, `COMPACT_KEEP_LAST`. `.env.example` updated with every key and a comment.
- **Policy table:** move `_policy` out of `routes/ask.py` into `policy/table.py`; default for unknown tools becomes `DENIED`.
- **Cache key:** `answer_key` hashes tool names, so a user with Gmail connected gets a different cache namespace than one without — correct, no change.
- **Prompt:** `system_agent.txt` gains the untrusted-content rule and a short connector-usage section; that bumps `prompt_version` and invalidates the answer cache — expected.
- **Migrations:** 1 for `connector_credentials`, 1 for `threads.compaction_log`.
- **Tests:** unit tests for compaction cut-point logic, vault round-trip, Postgres SQL guard, provenance wrapping/escaping, taint escalation; cassette integration tests per connector.
- **Order of work** (dependencies): 29 → 31 → 30 → 32 → 33/34 (no auth, quick wins) → 35 → 36 → 37 → 38 → 39 → 40. 39 is written *before* 36–38 are exposed to real users; it's placed late in the list but its provenance wrapper is used by every connector from the start.

---

## 3. Decisions needing your answer before implementation starts

1. **GPT-6 Astra**: model id, API endpoint/base URL, pricing.
2. **Native vs MCP** for Gmail/Slack/Discord/Postgres — recommend native (D-2).
3. **Vault key management**: Fernet key in `.env` acceptable for now?
4. **Google scopes**: testing mode with test users, or begin verification?
5. **Slack**: user token (act as user) vs bot token — recommend user token.
6. **Postgres**: per-user DSN via vault (recommended) vs one global read-only DSN.
7. **Taint policy**: approve the "untrusted content ⇒ outbound needs approval" rule, including `web_search`.
8. **Compaction defaults**: 60 % of context window trigger, keep last 8 messages, keep raw log — ok?

---

## Decision log

Append-only. `D-n` entries are decisions; `L-n` entries are things learned while implementing.

- **D-1 (2026-09-15)** Provider registry replaces `lru_cache`d `get_provider()` with a name-keyed registry; `OpenAIProvider` gains `base_url`. Rationale: an unknown "Astra" endpoint is most likely OpenAI-compatible; making the URL config avoids a new class per vendor.
- **D-2 (2026-09-15)** Phase 6 connectors are native Python tools built with the existing per-user closure pattern, not MCP servers. Rationale: MCP servers are spawned at process start and hold one credential; per-user tokens would require one server process per user per connector. The MCP manager upgrade (step 30) targets remote/third-party servers instead.
- **D-3 (2026-09-15)** Context compaction measures pressure with the provider-reported `input_tokens` of the previous turn instead of adding a tokenizer dependency. Rationale: it is exact for the model in use and already collected; a tokenizer would be approximate for non-OpenAI models anyway.
- **D-4 (2026-09-15)** `Budget` splits into per-turn context limit (triggers compaction) and cumulative spend cap (stops the run). Rationale: the existing single cumulative counter would stop long connector runs even after compaction freed the context window.
- **D-5 (2026-09-15)** The step-16 "summarization primitive" is currently an f-string; a real LLM summarizer is built first (`memory/summarize.py`) and shared by episodes and compaction. Rationale: the plan assumes it exists; better to make that true than to fork two summarizers.
- **D-6 (2026-09-15)** Unknown tool names default to `DENIED` instead of `SENSITIVE`. Rationale: default-allow was harmless with filesystem + search; with outbound connectors an unlisted tool must not be callable.
- **D-7 (2026-09-15)** Untrusted tool output escalates outbound tools to approval (taint tracking) rather than trying to sanitize the content. Rationale: sanitizing text is unwinnable; gating the *side effects* is enforceable in the loop and visible to the user through the existing HITL card.
- **D-8 (2026-09-15)** Connector tools that lack a vault credential for the requesting user are not registered for that request, instead of registering and returning an error. Rationale: keeps the tool list (and so the answer-cache key and the model's choices) honest.
