# Agent replies taking ~22 s ("Hey, I live in Jammu")

## Symptom

After the frontend rework, a trivial message in the chat UI — "Hey, i live in
Jammu!" — took about 22 seconds before the reply appeared. It felt like the
frontend changes had caused it.

## What was actually going on

The frontend was not the problem. The BFF hop (`web/app/api/chat/route.ts`)
costs ~40 ms, and the new `chat/page.tsx`, `auth.config.ts` and `proxy.ts`
add nothing measurable to a request. Timing the SSE stream straight against
FastAPI with a minted JWT (same question, same user) gave **8.3 s, 13.9 s and
6.9 s** for three identical runs — so the whole delay, and all of its
variance, was in the backend.

Two things had changed there at the same time:

1. **`DATABASE_URL` in `.env` now points at Neon in `ap-southeast-1`
   (Singapore)**, not the local docker-compose Postgres. Every query is a
   ~250–300 ms round-trip on a good moment, and the WSL2 → Neon path is
   erratic: measured fresh connections took 3 s, 5 s, 24 s, **131 s** and
   **261 s** at various points in the same hour (the same class of problem as
   the Google OAuth `ETIMEDOUT` note from earlier today). Docker is not
   available in this WSL distro, so the local database was not an option.

2. **The new memory features added several synchronous DB calls per request**
   (`profile_text`, the `remember` tool, `store_episode`), on top of the
   existing ones (`CheckpointStore.load`/`save` per step, `record_transaction`).
   All of them use sync SQLAlchemy `SessionLocal()` inside `async` code.

For "I live in Jammu" the agent makes two model turns (call `remember`, then
answer) and, before the fix, did roughly this many *serial* DB round-trips on
the critical path:

| Where                                  | Round-trips |
| -------------------------------------- | ----------- |
| `profile_text` (ping + select)         | 2           |
| `CheckpointStore.load` (always a miss on `/ask` — the run id is new) | 2 |
| `remember` tool (ping + insert + commit) | 3         |
| `CheckpointStore.save` after step 1    | 3           |
| `CheckpointStore.save` "done"          | 3           |
| `record_transaction` (ping + select + insert + commit) | 4 |
| `store_episode` (OpenAI embedding + ping + insert + commit) | 3 + API |
| **Total**                              | **~20 + embedding** |

At 300 ms each that is ~6 s of pure waiting even when the network is behaving,
and any one of them could stall for seconds when it was not. Then two
`gpt-5.5` turns (~2–4 s each, occasionally 10 s+; it is a reasoning model and
the path to `api.openai.com` also dropped 1 of 6 connects for 10 s during
testing).

Because the calls were synchronous, they also **blocked the event loop**: in
the pre-fix trace `tool_call` and `tool_result` arrive at the *same*
timestamp, because the SSE generator could not flush `tool_call` until the
`remember` insert had returned. The ledger/cache/episode bookkeeping ran
*after* the answer had been fully streamed but *before* the `done` event, so
the UI sat in "streaming" for another ~1–1.5 s after the last token.

### A correctness bug found on the way

`src/harness/api/routes/ask.py` had

```python
if profile:
    prompt_text = profile + "\n\n=== USER PROFILE ===\n" + profile
```

For any user with at least one memory this **replaced the entire system
prompt** (including the file-path rule) with the profile, twice. Fixed to
append to `prompt_text`. Side effect: prompts are now larger for users with
memories, so per-run cost went from ~$0.029 to ~$0.037 for this question.

## Changes made

All backend; no frontend files were touched.

**`src/harness/api/routes/ask.py`**
- Fixed the profile/system-prompt bug above.
- `profile_text` runs via `asyncio.to_thread` and fails soft (a DB blip logs a
  warning and the run continues without the profile) instead of failing the
  request.
- Ledger write, answer-cache write and episode storage moved into a
  background task (`_finish_run`, spawned by `_spawn_bookkeeping`, with strong
  task refs held in `_background`). The response / SSE `done` no longer waits
  for ~7 round-trips plus an embedding call. Each step is individually
  try/excepted and logged.

**`src/harness/agent/loop.py`**
- `store.load` runs in a worker thread.
- `store.save` goes through a `persist()` helper: saves are chained so they
  land in order, run in a worker thread, and only the `pending_approval` save
  is awaited (because `/approve` has to find it). Mid-run and final "done"
  saves are fire-and-forget; nothing on the response path reads them. Strong
  refs are held in `_pending_saves`.

**`src/harness/api/routes/approve.py`** — checkpoint load/save via
`asyncio.to_thread` (awaited; `run_agent` reads it immediately after).

**`src/harness/tools/builtin/remember.py`, `recall.py`,
`src/harness/db/episodes.py`** — the sync DB work inside the async handlers
now runs in `asyncio.to_thread`, so a slow insert no longer freezes every
other request and the SSE flush.

**`src/harness/db/base.py`** — `connect_args` with `connect_timeout=10` (a hung
SYN now fails in 10 s instead of minutes) and TCP keepalives
(`keepalives_idle=30` …) so WSL2's NAT stops silently dropping idle pooled
connections, which is what was forcing those slow reconnects in the first
place.

## Result

Same question, same user, warm worker, timed at the FastAPI SSE stream:

| | before | after |
| --- | --- | --- |
| time to `step 1` | 0.7–1.1 s | 0.8 s |
| `text_end` → `done` | 0.9–1.4 s | 0 ms |
| total (3 runs) | 8.3 / 13.9 / 6.9 s | 4.5 / 6.9 / 15.3* s |

\* that 15.3 s run was entirely one slow OpenAI turn (11 s between `step 2`
and `text_start`); nothing of ours runs in that gap any more. What remains is
the two `gpt-5.5` turns plus whatever the network does to them.

`tool_call` now streams to the UI ~0.3 s before `tool_result`, i.e. the
"running" card actually shows while the tool runs.

## What is still true / what to do about the rest

- **The database is still 300 ms away over a flaky path.** The remaining DB
  cost on the critical path is `profile_text` + the `remember` insert (~5
  round-trips, ~1.5 s). The real fix is a local Postgres for development
  (`docker compose up -d` once Docker Desktop's WSL integration is enabled for
  this distro), or a Neon branch in a closer region. `AUTH_PG_URL` for
  NextAuth is the same Neon instance but is only hit on sign-in, not per
  message.
- A cold worker (after `--reload`, or after a pooled connection dies) still
  pays a fresh connect, now capped at 10 s per attempt. If the first request
  after a code change is slow, that is why.
- `gpt-5.5` is a reasoning model; if 2–4 s per turn is too slow for chat,
  passing `reasoning_effort="low"` (or `"minimal"`) in
  `providers/openai_provider.py` is the lever. Not changed here — that is a
  quality/latency trade-off to decide deliberately.
- The `is_revoked()` check in `src/harness/auth/revocation.py` never returns
  `True` for a revoked token (it evaluates the comparison and discards it,
  returning `None`). Not a latency issue; noted for a follow-up.

## Test data to clean up

Timing probes were run as `users.id = 3` with the text "Hey, I live in
Jammu" (capital I, no "!"), each of which stored a memory and an episode.
Deleting them was blocked by the auto-mode permission rules, so run this
yourself if you want them gone (your own rows — memory 6, episode 16, and the
Bengaluru/born-in-Jammu ones — are not matched):

```sql
delete from episodes    where user_id = 3 and summary like 'User asked Hey, I live in Jammu. %';
delete from user_memory where user_id = 3 and content = 'User lives in Jammu.' and id in (5,7,8,9,10,11,12,13,14,15,16);
```

## How to measure this again

The probe used for the numbers above (mint a JWT with `jwt_secret` from
settings, POST to `/ask/stream`, print each SSE event with a timestamp):

```bash
.venv/bin/python - <<'EOF'
import asyncio, json, time, jwt, httpx
from harness.config import get_settings
s = get_settings()
tok = jwt.encode({"sub": "3", "role": "user", "exp": int(time.time())+300}, s.jwt_secret, algorithm=s.jwt_algorithm)
async def main():
    t0 = time.perf_counter()
    async with httpx.AsyncClient(timeout=120) as c:
        async with c.stream("POST", "http://localhost:8000/ask/stream",
                            headers={"Authorization": f"Bearer {tok}"},
                            json={"question": "Hey, I live in Jammu"}) as r:
            ev = None
            async for line in r.aiter_lines():
                if line.startswith("event:"): ev = line[6:].strip()
                elif line.startswith("data:") and ev != "text_delta":
                    print(f"{time.perf_counter()-t0:6.2f}s  {ev:18} {line[5:].strip()[:100]}")
asyncio.run(main())
EOF
```

Anything between `step N` and the next `text_start`/`tool_call` is the model;
anything between `text_end` and `done` is us.
