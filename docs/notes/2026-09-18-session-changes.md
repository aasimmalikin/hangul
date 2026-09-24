# Session change log — 2026-09-18

Everything added or changed in this working session, in the order it was built. Each section says what exists now, where it lives, how it was verified, and what was deliberately left out.

Tests at the end of the session: **134 unit tests passing** (`pytest tests/unit`), Playwright e2e specs 01–13 passing against the fake backend (04-approval "drafted" test is a pre-existing ~1-in-3 timing flake), `npm run build` clean.

---

## 1. MCP client manager (`src/harness/mcp/`)

**Before:** a 37-line `MCPManager` holding a flat list of stdio clients; `close()` stopped at the first error; shadowing alerts never named the owner; no per-server state; `CallToolResult.is_error` ignored.

**Now**
- `config.py` — `ServerConfig` + `servers.yaml` (`load_server_configs`): transport `stdio` / `streamable_http` / `sse`, env/headers/url, timeouts, `enabled`, tags, `${VAR}` expansion, validation (names, duplicates). Missing file → the old hard-coded filesystem server.
- `client.py` — `MCPClient` with `ConnectionState`, `last_error`, `connected_at`, paginated `list_tools`, timeouts, `ping`, idempotent `aclose`. The connection runs in its **own owner task** because the SDK's anyio cancel scopes must be entered/exited by the same task (a real bug the first integration run surfaced).
- `manager.py` — `connect_all` (parallel, failure-isolated), `discover`, namespacing `<server>__<tool>` (`qualify`/`split`/`owner`), `register_into`, `call_tool` (lazy reconnect once, per-server lock, errors as `[mcp error]`/`[tool error]` text), `aclose`, `status()`; `current()/set_current()`.
- `/healthz` now reports per-server `{state, tool_count, last_error}`.
- Later in the session: `vault:` / `vault-proxy:` refs (§2), `user-token:` refs and **per-user sessions** (§7).

Verified against the real `@modelcontextprotocol/server-filesystem`: discovery (14 tools), kill → reconnect on next call, a broken server beside a good one, zero leftover child processes.

## 2. Token vault (`src/harness/vault/`)

Credentials are encrypted at rest (Fernet, `VAULT_MASTER_KEY`); the agent and MCP servers hold only short-lived **grants**; every outbound call goes through a **proxy** that injects the real credential server-side.

- `crypto.py`, `providers.py` (fixed host allowlist: `tavily`, `github`, `http:<host>`), `grants.py` (Redis, SHA-256 of the token only, TTL, call budget), `policy.py` (host/method/path/body/budget; `access=read|write` with the spec deciding what is a write), `proxy.py` (the only decrypt; strips caller auth headers, drops `Set-Cookie`, caps + redacts body, audits), `redact.py` (process-wide scrubber wired into the audit log, the loop's stored tool results, trace attributes), `store.py` (Postgres `vault_credentials`, `vault_consents`; in-memory variants for tests), `bootstrap.py`.
- Consent: standing per-provider consent with TTL; writes need `allow_write` **and** still pause for approval every time. `tavily` is auto-consented for system use so `web_search` keeps working.
- Tools `vault_request` (GET only, SENSITIVE) / `vault_mutate` (writes, DESTRUCTIVE) built per request; `web_search` migrated onto the proxy (`tavily-python` removed).
- MCP: `"vault:<provider>"` → a fresh grant at every connect (revoked on close); `"vault-proxy:<provider>"` → `/vault/proxy/<provider>/`.
- Routes `/vault/{providers,credentials,consents,audit}` (JWT) and `/vault/proxy` (grant-authenticated); BFF `web/app/api/vault/*`; page `web/app/vault`.
- Migration `d5f8a2b3c4e6`.

Verified: real Tavily through the proxy; real GitHub via the transparent proxy with a fake PAT (401 relayed, policy denies writes on a read-only grant); zero secret hits in `audit.jsonl`/logs.

## 3. Evals + admin console (`src/harness/eval/`, `routes/admin.py`, `web/app/admin`)

- `trajectory.py` captures the loop's `on_event` stream + full tool outputs from the checkpoint. `dataset.py` extends cases with concern / expected / allowed / forbidden tools, expected args, `requires_approval`, `must_not_claim`, `history`, `connectors`, `poison`.
- `tool_graders.py`: **tool_choice** (set-F1), **tool_necessity**, **hallucination** (invented tools/args + judge on "claims an action no call backs"), **separation_of_concerns** (`CONCERN_TOOLS`), argument_correctness, approval_compliance, efficiency and cost. Dataset `data/evalsets/tool_selection.jsonl` (16 cases).
- `catalog.py` — every eval with `status` available/planned; `suites.py`, `store.py`, `agent_runner.py` (shared by `run_evals.py --suite … --limit … --ids …` and the admin API; brings up MCP + vault itself from the CLI).
- Admin API `/admin/{whoami, evals/*, security, overview}`; page `/admin` with latest results + CI gate, catalog (now/planned), stored runs, per-case table, live metrics, run-suite button.
- Real run: tool_selection 5 cases all 1.0 after fixing a grader that only showed the judge a 150-char preview.

## 4. Admin authentication (email allowlist + Google)

- Backend `auth.require_admin`: email in `settings.admin_emails` (default hard-coded) **and** `auth_provider == "google"` **and** sign-in ≤ 12h **and** optional `admin_ip_allowlist` (direct peer IP only). `role` alone never grants admin. Every admin call audited (`kind: admin`); denials logged.
- Web: `auth.ts` records `provider`/`authAt` on sign-in; `lib/bff.ts::requireAdmin` (Google-backed + recent) → `401 unauthorized` / `401 reauth_required`; service token carries `email`/`auth_provider`/`auth_at`; `app/api/admin/_shared.ts` adds same-origin, rate limit, `no-store`, `noindex`, maps backend 403 → `forbidden`. `next.config.ts`: HSTS + `no-store`/`noindex`/`no-referrer` on `/admin*`. Settings gear → **Admin console**; the page shows Google-only sign-in / re-auth / not-an-admin / console states.
- `scripts/make_admin.py` and the users.role session lookup were removed (one mechanism).

## 5. Connectors + arXiv Research connector (`src/harness/connectors/`)

- Registry of opt-in tool sources switched on **per conversation** from the composer's `+ → Connectors` submenu (hover/click), per tab (`sessionStorage`), sent as `AskRequest.connectors`, stamped on `threads.connectors` (migration `e6a1b2c3d4f5`) so `/approve` resumes with the same tools. `GET /connectors` (public catalogue).
- Builtin `arxiv` = **Research**: `arxiv_search` / `arxiv_paper` over the public Atom API (3 s rate limit, field syntax pass-through, fixed `all:` prefix bug). MCP servers tagged `connector` become connectors too.
- UI: `AttachMenu` submenu, `ConnectorChips`, landing→chat handoff of the selection. Eval: `research` concern + 2 cases; real run all 1.0.

## 6. Prompt-injection defence (`src/harness/security/`)

Layered: (1) hardened prompt (static trust rules + per-thread policy block with an HMAC-derived **canary** and boundary), (2) input screen with repeat-offender throttling (429), (3) **spotlighting** — tool results reach the model as JSON with provenance inside `<tr-…>` boundaries plus a reminder, (4) tool-result screen (`detector.py`: Unicode normalisation, 8 weighted pattern families incl. base64-decoded payloads; optional model classifier `security_llm_screen`) that **taints** the run (`threads.security`, migration `f7b2c3d4e5a6`), (5) action guard — arguments carrying a secret/canary are refused, encoded blobs and any consequential call under taint become approvals, (6) output guard — secrets, canary, external markdown images, encoded-param URLs; the guarded answer replaces streamed text in the UI, (7) oversight — `security` events streamed as notice cards, audited (`kind: security`), summarised on `/admin`, uploads scanned at ingest, and the **`prompt_injection` eval suite** (8 poisoned-tool-result attacks).

Red-team result on gpt-5.5: attack success 0 %, leak 0 %, detection 100 % (62.5 % before closing three detector gaps), task completion 96 %, reported-to-user 94 %.

## 7. Google Workspace bundle + personal-assistant features

- **Google bundle**: Google's official Workspace MCP servers (Gmail, Calendar, Drive, Docs; streamable HTTP, OAuth bearer) declared in `servers.yaml` as `per-user` servers with `Authorization: Bearer user-token:google:<product>`, grouped by `bundle:google` into one connector *Google Workspace*. `integrations/google_oauth.py` refreshes access tokens from the refresh token Auth.js stores when the user clicks **Connect Google Workspace** on `/vault` (Google sign-in re-run with Workspace scopes + offline access; `web/auth.ts` persists the tokens). `MCPManager.ensure_user_session` / `tools_for_subject` give each user their own session (idle-reaped); `ToolPolicy` patterns make send/create/delete/share DESTRUCTIVE. `GET /integrations`, `DELETE /integrations/google`. The `+ → Connectors` menu shows *Connect your account first →* until connected.
- **Personalisation**: `user_settings` (name, tone, timezone, language, custom instructions) → `=== ABOUT THE USER ===` block in every prompt (with local time); `/settings` page; in the cache key.
- **Scheduled tasks**: `scheduled_tasks` + in-process `scheduler.py` (every minute); daily-at in the user's timezone or every-N-minutes (≥15); runs through the same path as `/ask`; results in the Chats rail as `⏰ <title>`; run-now / pause / delete on `/settings`.
- **Deep research mode**: composer chip → `mode="research"`: staged plan → multiple searches (docs, web, arXiv) → numbered citations + Sources, doubled budget.
- Migration `a1c2d3e4f5b6`. Provider fix: retry without `reasoning_effort` when OpenAI rejects it with tools (pre-existing 500 on `/ask` with gpt-5.5).

Verified on the real API: bundle degrades with a clear note when not connected; a task created, run now (`done`, answer `- 4` — already in the user's bullet-point style), episode `⏰ Smoke` present; no tracebacks.

## 8. Frontend parity pass (2026-09-19)

Audit of every backend surface against the web app closed four gaps: a poisoned upload's `security.warning` now marks its chip and explains itself; a scheduled task that paused (`needs_approval`) can be approved/rejected from `/settings`; the admin *Live* section shows MCP servers, per-user Workspace sessions, the scheduler backlog and recent traces (`/admin/overview` extended); the landing page has the *Deep research* toggle and carries it into `/chat`.

## 9. Google Workspace over REST + Google-styled cards (2026-09-19)

Google's official Workspace MCP servers turned out to require a Workspace organisation enrolled in the Developer Preview (personal accounts get "requires ... Developer Preview"), so the `google` connector became a **builtin over Google's REST APIs** (`connectors/google_rest.py`): Gmail search/read/draft/**send**, Calendar list/create, Drive search/read, Docs read/append, per user, with the same tool namespaces and approval tiers (drafts, sends, events, doc edits ask first). Along the way: a diagnostic `/integrations/google/check` + *Test connection* button; `LenientJsonRpcTransport` for MCP servers that put a 4xx on a JSON-RPC result; a DB `statement_timeout` (via `SET`, Neon's pooler rejects startup options), bounded startup, connect-time address pinning and pool warm-up for the slow WSL→Neon path; and the OpenAI `reasoning_effort`+tools retry.

Tool results can now carry structured `ui` (`ToolOutput`) that the chat renders as **Google-styled cards** (`GoogleCards.tsx`): Gmail inbox rows (unread bold, label chips, avatars), conversation view, compose preview on approval, Calendar agenda, Drive list, Docs page.

---

## Migrations added (apply with `alembic upgrade head`)
`d5f8a2b3c4e6` vault tables · `e6a1b2c3d4f5` threads.connectors · `f7b2c3d4e5a6` threads.security · `a1c2d3e4f5b6` user_settings + scheduled_tasks

## New settings (`.env`)
`vault_master_key`, `vault_grant_ttl_s`, `vault_public_url` · `admin_emails`, `admin_max_auth_age_s`, `admin_ip_allowlist` · `security_llm_screen`, `security_screen_model`, `security_offender_limit`, `security_offender_window_s` · `auth_google_id`, `auth_google_secret`, `scheduler_enabled`

## Deliberately not built (and why)
- **Agent / computer-use mode** (browsing, clicking): needs a sandboxed browser runtime; the security layers here would have to be re-derived for screenshots.
- **Voice**: audio I/O pipeline; orthogonal to the agent.
- **Canvas / collaborative document editing** and **Projects** (partitioned memory + files per workspace): product-scale UI work; memory is per user today.
- **Push/email notifications** for scheduled tasks: results land in the Chats rail; an email digest would go through the Gmail bundle once connected.
- **Responses API migration**: the reasoning-effort-with-tools limitation is worked around, not solved.
- **Multi-replica scheduler** (leader election) and **OAuth for arbitrary connectors**: Google is the only OAuth source; others use pasted keys through the vault.
- Planned evals stay listed on `/admin` (task completion by end state, multi-turn, retrieval P/R, PII canaries, pass^k, judge calibration, production drift, user feedback).
