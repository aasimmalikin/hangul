# Memory endpoints review — 2026-09-17

Review of the new `GET /memory` / `DELETE /memory/{id}` backend route and the
matching BFF routes under `web/app/api/memory/`. Two of the problems would
have taken the whole API down or made every memory request fail; the rest
were convention drift from what the other routes do.

## Files touched

| File | Change |
|---|---|
| `src/harness/api/routes/memory.py` | rewritten (see below) |
| `src/harness/db/memory.py` | `deactivate_memory` now returns `bool` |
| `web/app/api/memory/route.ts` | rewritten on `lib/bff.ts` |
| `web/app/api/memory/[id]/route.ts` | rewritten on `lib/bff.ts` |
| `tests/unit/test_memory_routes.py` | new — 4 tests, fakes only |

## Backend — `src/harness/api/routes/memory.py`

### 1. Typo in the import crashed the entire API at startup (critical)

```python
from hanress.db.memory import list_active, deactivate
```

`hanress` is not a package. Because `api/app.py` imports this module at the
top, `uvicorn harness.api.app:app` raised `ModuleNotFoundError` before a
single route was registered — not just `/memory` but `/ask`, `/healthz`,
everything. Reproduced with `python -c "import harness.api.app"`.

**Fix:** `from harness.db.memory import deactivate_memory, list_active`.

### 2. Imported name did not match the called name

The import asked for `deactivate`, but the handler called
`deactivate_memory(...)`. `db/memory.py` only defines `deactivate_memory`,
so even with the typo fixed the import would have failed with `ImportError`.

**Fix:** import and call `deactivate_memory`.

### 3. `await` on synchronous functions → `TypeError` on every request

```python
rows = await list_active(user["user_id"])
await deactivate_memory(user["user_id"], memory_id)
```

Both db functions are plain synchronous SQLAlchemy. `await <list>` raises
`TypeError: object list can't be used in 'await' expression`, so `GET /memory`
would have returned 500 every time. It also would have blocked the event loop
during the DB round-trip.

**Fix:** `await asyncio.to_thread(list_active, ...)` — the same pattern
`tools/builtin/recall.py` and `routes/ask.py` already use for this module.

### 4. `DELETE` reported success for rows it did not delete

`deactivate_memory` silently did nothing when the id did not exist, was
already inactive, or belonged to another user — and the route then returned
`{"deleted": id}` regardless. A client could not tell a real delete from a
no-op.

**Fix:** `deactivate_memory` now returns `True` only when it actually flipped
a row owned by the caller; the route raises `404 memory not found` otherwise.
The three cases are deliberately indistinguishable so ids cannot be probed
across users (same stance as `CheckpointStore.claim_pending` on `/approve`).

### 5. Response lacked `created_at`

The rows are already ordered newest-first; without a timestamp the UI cannot
show *when* something was learned. Added `created_at: datetime` to
`MemoryItem`.

## BFF — `web/app/api/memory/route.ts` and `[id]/route.ts`

### 6. Wrong JWT subject — every request would have failed with 500 (critical)

```ts
const token = await mintServiceToken(session.user.email, "user")
```

`mintServiceToken` documents that `sub` is the NextAuth `users.id`, and
`db/memory.py` casts it with `int(user_id)` because the column is an integer.
Sending the email means `int("aasimmallikk@gmail.com")` → `ValueError` →
500 on every call. Every other BFF route passes `who.userId`
(`session.user.id`, set in `auth.config.ts`).

Even if the cast had worked, the memory would have been looked up under a
different identity than the one the `remember`/`recall` tools write under,
so users would always have seen an empty list.

**Fix:** use `requireUser()` → `who.userId`.

### 7. Bypassed `lib/bff.ts` entirely

CLAUDE.md: *"BFF routes all go through `web/lib/bff.ts` … Add new routes the
same way."* The handwritten routes had none of:

- `assertSameOrigin` on the state-changing `DELETE` (CSRF guard)
- per-user `rateLimit`
- `upstream()` with a timeout — a hung FastAPI would hang the request forever
- `{detail, code}` error bodies — errors were plain-text `"Unauthorized"`,
  which `lib/apiError.ts` and the UI cannot branch on
- `relayUpstreamError` — backend 4xx/5xx were relayed raw, and a backend 401
  (rejected service token) would have been shown to the user as if *their*
  session were bad

Also `process.env.FASTAPI_URL` was interpolated unchecked; `upstream()`
turns a missing value into a clean 502.

**Fix:** both routes rewritten with the same shape as `api/upload/route.ts`:
origin check (DELETE only) → `requireUser` → `rateLimit("memory:<id>", 60/min)`
→ `upstream(..., { timeoutMs: 10_000 })` → `relayUpstreamError`.

### 8. `DELETE` id not validated

`/memory/abc` was forwarded as-is. Now rejected in the BFF with
`400 bad_request` before it reaches the backend (the backend would 422 anyway
via the `int` path param, covered by a test).

### 9. GET response was cacheable

Personal data; added `Cache-Control: private, no-store` and `cache: "no-store"`
on the upstream fetch.

## Verification

```
.venv/bin/python -c "import harness.api.app"     # import ok
.venv/bin/pytest tests/unit                       # 14 passed (4 new)
cd web && npx tsc --noEmit && npx eslint app/api/memory   # clean
```

The new tests cover: GET returns only the caller's active rows with the
expected shape; DELETE on an own row succeeds once then 404s; DELETE on
another user's row is 404 and leaves it active; non-numeric id is 422.

## Not changed

- `ruff` flags `B008` (`Depends(...)` in argument defaults) on the new route.
  That is the standard FastAPI idiom and every existing route
  (`approve.py`, `ask.py`, …) triggers the same warning, so I left it
  consistent rather than special-casing one file.
- No frontend page consumes these endpoints yet; this note only covers the
  API surface.

---

# Part 2 — Memory rail on `/chat` (frontend)

Added the same day, after the API review above. A left-hand panel on the
chat page that shows the signed-in user's memory and lets them delete items.

## Files added / changed

| File | Change |
|---|---|
| `web/components/hangul/MemoryPanel.tsx` | new — the rail |
| `web/app/globals.css` | new `.h-sidebar`, `.h-sidebar-scroll`, `.h-memory-item`, `.h-memory-dots`, `.h-menu-danger` classes |
| `web/app/chat/page.tsx` | mounts the rail left of the conversation; bumps a refresh key when a run ends |
| `web/tests/e2e/fake-backend.mjs` | `GET /memory`, `DELETE /memory/:id` stand-ins, seeded per user |
| `web/tests/e2e/helpers.ts` | `backendState()` type gains `memory` |
| `web/tests/e2e/07-memory.spec.ts` | new — 4 tests |

## What the rail does

- **Placement** — `<aside class="h-sidebar">` on the left, 264 px, its own
  column beside the conversation + composer (`page.tsx` wraps them in a
  flex row under the header/status banner). Rendered only when
  `authStatus === "authenticated"`; signed-out visitors see the page exactly
  as before. Hidden below 860 px viewport width so the chat still fits on a
  phone.
- **Scrolling** — the list is a `.h-sidebar-scroll` region with
  `overflow-y: auto`, `min-height: 0` and a thin themed scrollbar
  (`scrollbar-color: var(--faint) transparent`; WebKit equivalent). A long
  history scrolls inside the rail; the header and footer note stay put and
  the composer is never pushed off-screen.
- **Items** — newest first (the backend's order), each with a kind icon
  (`preference` → heart, `fact` → info, `correction` → pencil), the text,
  and a relative date (`today`, `yesterday`, `6d ago`, else `Sep 10`).
- **⋯ on hover** — `.h-memory-dots` is `opacity: 0` and becomes `1` on
  `.h-memory-item:hover`, when its menu is open (`.is-open`), or on
  keyboard focus (`:focus-visible`) so it is reachable without a mouse.
- **Delete menu** — clicking ⋯ opens an `.h-popover` (same surface as the
  profile menu) with one entry, **Delete** (`.h-menu-danger`). It is
  `var(--fg)` at rest and turns `var(--err)` on hover/focus. Click outside
  closes it.
- **Deleting** — the row is removed from the list immediately (optimistic),
  then `DELETE /api/memory/:id` is sent. On failure (anything but 200/404)
  the row is put back and the error is shown inline with a Retry. A 404 is
  treated as "already gone" (another tab, or the agent superseded it) and
  the optimistic removal stands.
- **Deactivate, not erase** — nothing on the frontend hard-deletes. The
  backend flips `active=false`; from then on the item is out of the
  profile block, out of `recall`, and out of this list. The rail's footer
  says so: *"Deleting hides a memory from you and the agent; it is kept,
  inactive, on the server."*
- **Stays fresh** — `refreshKey` is the count of finished runs (`data-run`
  parts) plus resolved approvals. Both are moments the agent may have
  called `remember`, so a new memory shows up as soon as the answer ends,
  with no reload. There is also a manual refresh button in the header.
- **Auth** — a 401 from the BFF is routed through the page's existing
  `handleFailure`, which opens the sign-in modal the same way an expired
  session does mid-chat.

## Theme alignment

No colours are hard-coded. Everything is `var(--surface)`,
`--surface-border`, `--surface-hover`, `--bubble`, `--fg`, `--muted`,
`--faint`, `--err`, so light and dark both work (verified in dark). The
heading uses `.h-display` (Fraunces) like the other headings, the menu is
`.h-popover`, the buttons are `.h-btn-ghost`, the icons are Tabler
(`ti-brain`, `ti-dots`, `ti-trash`, `ti-refresh`). The new classes live in
the same `@layer components` block as the rest of the `.h-*` set, per
`docs/notes/2026-09-15-frontend-theme-unification.md`.

## Tests

`07-memory.spec.ts`, run against the fake backend with the production build:

1. lists three seeded items newest-first, and the list region has
   `overflow-y: auto`
2. ⋯ is `opacity: 0` until the row is hovered; Delete's colour differs from
   `--err` at rest and equals it on hover; after clicking, the row is gone
   from the UI, the backend still has all three rows with that one
   `active: false`, and it is still gone after a reload
3. a `502` on DELETE restores the row and shows the error
4. signed-out visitors do not see the rail

Full suite: `npm run test:e2e` → **43 passed** (39 existing + 4 new), so
the layout change did not disturb the other pages.

## Notes

- The `react-hooks/set-state-in-effect` lint rule fires on the
  fetch-on-mount effect. State is set after an `await`, not synchronously,
  so it is a false positive; it carries the same `eslint-disable-next-line`
  the chat page already uses for its restore-on-mount effect.
- The rail is hidden, not collapsible, on narrow screens. A toggle would be
  the natural next step if memory needs to be reachable on mobile.

---

# Part 3 — "Chats" rail, bottom half only (revision)

Same day, second pass on the rail from Part 2, after feedback.

## What changed

| File | Change |
|---|---|
| `web/components/hangul/MemoryPanel.tsx` | heading **"Memory" → "Chats"**, brain icon removed; panel wrapped in a `<section class="h-sidebar-panel">` |
| `web/app/globals.css` | `.h-sidebar` is now a transparent full-height column with `justify-content: flex-end`; new `.h-sidebar-panel` (`height: 50%`) carries the surface, top/right border and rounded top-right corner |
| `web/tests/e2e/07-memory.spec.ts` | asserts the new heading, no icon, bottom-half geometry, and that the rail appears on sign-in |

### 1. Title and icon

The heading now reads **Chats** (Fraunces, `.h-display`, same size as
before) followed by the count. The `ti-brain` icon is gone. The empty-state
copy and the footer no longer use the word "memory" either ("Nothing here
yet…", "Deleting hides an item from you and the agent; it is kept,
inactive, on the server."). The ⋯ button's accessible name is "Options".

Test ids (`memory-panel`, `memory-item`, `memory-delete`) and the API
routes are unchanged — this is a label change, not a data-model change.

### 2. Bottom half of the left side only

Before, the rail was a full-height surface. Now:

- `.h-sidebar` — still 264 px wide and full height so the conversation
  column keeps the same width, but **no background and no border**; it is
  a flex column with `justify-content: flex-end`.
- `.h-sidebar-panel` — `height: 50%`, `min-height: 0`, flex column. This is
  the visible panel: `var(--surface)` background, `0.5px` top and right
  border in `var(--surface-border)`, `border-top-right-radius: 14px`.
  Header, scrolling list (`.h-sidebar-scroll`, unchanged) and footer live
  inside it.

So the top half of the left side is clear page background; the list starts
at the vertical midpoint and scrolls within the lower half. The e2e test
measures this: the section's top edge is at ≥ 50 % of the column height and
its bottom edge coincides with the column's.

### 3. Shown as soon as the user signs in

No code change was needed: the rail is rendered when
`useSession().status === "authenticated"`, which flips the moment NextAuth
has a session, and the panel fetches on mount. The e2e test now covers it
explicitly: signed-out → no rail; sign in → rail visible with the three
seeded items.

## Verification

- `tsc --noEmit` and ESLint clean.
- `07-memory.spec.ts` → **4 passed**.
- Full suite (`npm run test:e2e`) → 42 passed, 1 failed:
  `04-approval.spec.ts › the file content is shown as it is drafted…`.
  That test is unrelated to the rail (it checks the streaming
  `tool_pending`/`tool_args_delta` draft card) and is **flaky**: re-running
  it in isolation it passed 1 in 3, failing on a different assertion each
  time (`data-status`, then `tool-draft` not found within 10 s). It also
  passed in the first full run of Part 2 with the rail present. Its timing
  depends on the fake backend's streaming delays, not on this change; it
  belongs with the uncommitted streaming work in the tree
  (`fake-backend.mjs`, `04-approval.spec.ts`, `agent-activity.tsx`).

---

# Part 4 — Smaller heading, full-height surface, rail on the landing page

Third pass on the rail, same day.

| File | Change |
|---|---|
| `web/components/hangul/MemoryPanel.tsx` | "Chats" heading 16 px → **14 px**, header padding tightened |
| `web/app/globals.css` | `.h-sidebar` has its `var(--surface)` background and right border back (covers the full left side); `.h-sidebar-panel` keeps `height: 50%` but is now just a hairline-separated lower half of that surface (no own background / radius) |
| `web/app/page.tsx` | landing page mounts `<MemoryPanel>` beside the centred content when `status === "authenticated"` |
| `web/tests/e2e/07-memory.spec.ts` | geometry test updated; new landing-page test |

### 1. Heading

`Chats` is `.h-display` at **14 px** (was 16). Count and refresh button
unchanged.

### 2. Whole left side covered, list in the lower half

The request was to have the left side covered again while keeping the
previous "start from the lower half" arrangement, so:

- `.h-sidebar` — 264 px, full height, `var(--surface)` background and a
  `0.5px` right border in `var(--surface-border)`. This is the part that
  now covers the entire left side.
- `.h-sidebar-panel` — still `height: 50%` at the bottom of that column,
  separated from the empty upper half by a `0.5px` top border. Header,
  scrolling list and footer are inside it, exactly as before.

The e2e geometry check asserts the column's bottom edge is the viewport
bottom, the section starts at ≥ 50 % of the column, and the heading is
14 px.

### 3. On the landing page too

`app/page.tsx` had no rail; it only appeared once the user reached `/chat`.
The landing page's centred block is now wrapped in a flex row, with the
same `<MemoryPanel>` on the left when the session is authenticated.

- `<main>` switched from `min-height: 100vh` to `height: 100vh` so the rail
  has a definite height for its 50 % split; the content column gets
  `overflow-y: auto` so nothing is cut off on a short window.
- A 401 from the rail on the landing page opens the sign-in modal via the
  page's existing `askToSignIn`.
- Below 860 px the rail is hidden here as on `/chat`, so the mobile landing
  page is unchanged.

### Verification

- `tsc --noEmit`, ESLint clean; `next build` OK.
- `07-memory.spec.ts` (5 tests, incl. the new landing-page one) +
  `01-auth-gate.spec.ts` + `05-upload.spec.ts` (the specs that drive the
  landing page) → **13 passed**.
- Screenshot-verified in dark mode: rail visible on `/` immediately after
  sign-in, list in the lower half, composer and prompt chips centred in the
  remaining width.

---

# Part 5 — Full-height rail again, smaller "Chats"

Fourth pass, same day. The lower-half arrangement from Parts 3–4 is
dropped in favour of the original full-height layout from Part 2.

| File | Change |
|---|---|
| `web/components/hangul/MemoryPanel.tsx` | "Chats" heading 14 px → **12 px**; removed the empty-upper-half placeholder comment |
| `web/app/globals.css` | `.h-sidebar` no longer `justify-content: flex-end`; `.h-sidebar-panel` is `flex: 1` (was `height: 50%`) with no top border |
| `web/tests/e2e/07-memory.spec.ts` | geometry check: section top == column top and section height == column height; heading is 12 px |

### Layout

The rail now fills the entire left column from under the header to the
bottom of the viewport, as in Part 2: fixed "Chats" header at the top, the
scrolling list (`.h-sidebar-scroll`) taking all remaining height, and the
"kept, inactive" footer pinned at the bottom. The `.h-sidebar-panel`
wrapper is kept (it is what the geometry test measures) but is now just a
`flex: 1` column inside the surface.

Everything else from earlier parts is unchanged: shown on `/` and `/chat`
as soon as the session is authenticated, ⋯ on hover, red Delete on hover,
optimistic removal with rollback, deactivate-not-erase, hidden under 860 px.

### Verification

- `tsc --noEmit`, ESLint clean; `next build` OK.
- `07-memory.spec.ts` → **5 passed**.
- Screenshot-verified on `/` in dark mode: rail spans header-to-bottom,
  12 px heading, list starts at the top.

---

# Part 6 — Drag to resize the rail

| File | Change |
|---|---|
| `web/components/hangul/MemoryPanel.tsx` | width state + drag handle (`startDrag`, `commitWidth`, keyboard handling) |
| `web/app/globals.css` | `.h-sidebar` gets `position: relative`; new `.h-sidebar-handle` |
| `web/tests/e2e/07-memory.spec.ts` | new drag test |

### Behaviour

- A **grip on the right edge** of the rail (`.h-sidebar-handle`, 8 px wide,
  straddling the border, `cursor: col-resize`). Invisible at rest; shows
  as a `var(--surface-border)` strip on hover, focus, and while dragging.
- **Left-click and drag** moves the edge; the rail follows the pointer
  live. Right/middle button are ignored (`e.button !== 0`).
- Bounds **200–480 px** (`WIDTH_MIN`/`WIDTH_MAX`), default 264. Dragging
  past a bound just stops there.
- **Double-click** the grip resets to 264.
- **Keyboard**: the grip is a focusable `role="separator"` with
  `aria-valuenow/min/max`; ← / → nudge by 16 px, Home / End jump to the
  bounds.
- The width is **remembered per browser** in `localStorage`
  (`hangul:chats-width`) and restored on the next visit — a per-viewer
  convenience, so it lives in `localStorage` rather than in the session
  thread. Restored in an effect (not the initial state) so server and
  client render the same 264 px first paint. All storage access is in
  try/catch for private mode.

### Implementation notes

- Uses Pointer Events with `setPointerCapture` on the grip, so the drag
  keeps tracking even when the pointer leaves the strip or the window, and
  a `pointercancel` ends it cleanly. `touch-action: none` on the grip so
  it also works with a finger/pen.
- While dragging, `document.body` gets `cursor: col-resize` and
  `user-select: none` so the text in the conversation does not get selected
  as the mouse sweeps across it; both are cleared on release.
- Width is applied as an inline `style={{ width }}` on the `<aside>`,
  overriding the CSS default. Both pages that mount the rail (`/`, `/chat`)
  get it, and they share the stored width.

### Verification

- `tsc --noEmit`, ESLint clean; `next build` OK.
- New test: a real `page.mouse` drag of 100 px → 364 px wide and
  `aria-valuenow="364"`; reload → still 364; drag 600 px → clamps at 480;
  double-click → back to 264. `07-memory.spec.ts` → **6 passed**.
- Screenshot-verified mid-drag: grip highlighted, rail at ~380 px,
  conversation column reflowing.

---

# Part 7 — Sigil + wordmark on the landing page

| File | Change |
|---|---|
| `web/components/hangul/AppHeader.tsx` | new optional `wordmarkHref` prop (default `"/"`), passed through to `<Wordmark href>` |
| `web/app/page.tsx` | `showWordmark={false}` → `wordmarkHref={null}` |
| `web/tests/e2e/07-memory.spec.ts` | landing test asserts the header mark (sigil SVG + "Hangul") is visible and sits above the rail |

The landing page was the one page that hid the header wordmark (it relied
on the big sigil in its hero). With the Chats rail now on that page, the
top-left looked empty above it. The header now shows the same
`<Wordmark>` (22 px `HangulSigil` + "Hangul" in Fraunces, tight tracking)
as every other page — no new markup or styling, just the shared component
turned on, so it is theme-aligned by construction.

Per `Wordmark`'s own contract, it is rendered with `href={null}` here
(a plain `<span aria-label="Hangul">`, not a link) because linking to `/`
from `/` is pointless. `AppHeader` grew a `wordmarkHref` prop to allow
that; `/chat` still gets the default link back home. The hero sigil is
unchanged.

### Verification

- `tsc --noEmit`, ESLint clean; `next build` OK.
- `07-memory.spec.ts` → **6 passed**; `01-auth-gate.spec.ts` (drives the
  landing page) still green.
- Screenshot-verified: sigil + "Hangul" top-left, Chats rail directly
  beneath, hero and composer centred in the remaining width.

---

# Part 8 — Landing-page prompts start a fresh conversation

| File | Change |
|---|---|
| `web/app/chat/page.tsx` | `handoffRef`: when the page is entered with `?q=`, the tab's saved thread is cleared instead of restored |
| `web/tests/e2e/02-chat.spec.ts` | new test walking Draft a note → Check the web → Search my documents |

## The problem

The three prompt chips on `/` ("Search my documents", "Check the web",
"Draft a note") — and a typed question — navigate to `/chat?q=<text>`.
On mount, `/chat` restores the tab's previous thread from `sessionStorage`
(`hangul:chat:<user id>`) and *then* sends `q`. So going back to `/` and
clicking a different chip appended the new question to the old
conversation, and sent the old messages as `history`, instead of starting
over.

## The fix

`/chat` now distinguishes two ways of arriving:

- **With `?q=`** — a hand-off from the landing page. This is a new
  conversation: the saved thread is cleared (`clearThread(storageKey)`),
  nothing is restored, and the question is sent with empty history.
- **Without `?q=`** — a refresh, back/forward, or the wordmark link. The
  thread is restored exactly as before.

The flag is captured once at mount in a ref (`handoffRef = useRef(Boolean(q))`)
because the page strips `q` from the URL right after sending; if it were
read live, the very next re-render would look like a "no `q`" arrival.
That is also what keeps the existing "refresh keeps the thread; `?q=` is
consumed once" test green.

## What is and is not kept

- Nothing server-side is lost. Every run remains checkpointed by
  `run_id`, cost stays in the ledger, and anything the agent stored with
  `remember` persists and still shows in the Chats rail.
- The previous *transcript* is not shown anywhere after the new chat
  starts — that was already the case for "New chat" and for opening a new
  tab. Summarising a closed thread into the `episodes` table
  (`harness.db.episodes.store_episode`) exists in the backend but is not
  wired to anything yet (nothing calls it), so past conversations cannot be
  listed or reopened. That is the natural next step if a real chat history
  is wanted; it was not part of this change.

## Verification

- `tsc --noEmit`, ESLint clean (one pre-existing warning in `page.tsx`);
  `next build` OK.
- New test: Draft a note → follow-up (4 bubbles) → back to `/` → Check the
  web → exactly 2 bubbles, old text absent, backend sees `history: 0` →
  Search my documents → again 2 bubbles → plain reload keeps those 2.
- `02-chat.spec.ts` + `01-auth-gate.spec.ts` → **14 passed**, including the
  earlier `?q=` and sessionStorage tests.

---

# Part 9 — The rail becomes a real chat history

Until now the "Chats" rail showed `user_memory` rows — facts the agent
stored with `remember` ("prefers short answers"), which is why the entries
looked stale. The request was for it to list every conversation, updated
as soon as the user is back on the landing page. That needs a
conversation store, which the backend already had a table for
(`episodes`, "past conversations summarised and embedded") but nothing
ever wrote to.

## Files

| Layer | File | Change |
|---|---|---|
| DB | `alembic/versions/b3d9e1f2c4a5_episodes_title_active.py` | **new migration**: `episodes.title`, `episodes.active`, `episodes.updated_at`, unique `(user_id, thread_id)` — run `alembic upgrade head` |
| DB | `src/harness/db/models.py` | `Episode` gains those columns + the unique constraint |
| DB | `src/harness/db/episodes.py` | `store_episode` is now an **upsert by (user, thread_id)** and returns the id; new `list_episodes`, `deactivate_episode`; `recall_episodes` skips hidden rows |
| API | `src/harness/api/routes/episodes.py` | **new**: `GET /episodes`, `POST /episodes`, `DELETE /episodes/{id}` |
| API | `src/harness/api/app.py` | router registered |
| Tests | `tests/unit/test_episode_routes.py` | **new**, 4 tests (fakes; no DB, no embedding call) |
| BFF | `web/app/api/chats/route.ts`, `web/app/api/chats/[id]/route.ts` | **new** GET / POST / DELETE through `lib/bff.ts` |
| UI | `web/components/hangul/ChatsPanel.tsx` | renamed from `MemoryPanel.tsx`; reads `/api/chats`, shows title + last-touched time |
| UI | `web/app/chat/page.tsx` | conversation id in the saved thread; saves after every completed run; `data-testid="thread"` on the message list |
| UI | `web/app/page.tsx` | mounts `ChatsPanel` |
| E2E | `web/tests/e2e/fake-backend.mjs`, `helpers.ts` | `/episodes` stand-ins (per user, upsert, deactivate) |
| E2E | `web/tests/e2e/07-chats.spec.ts` | renamed from `07-memory.spec.ts`, rewritten around real conversations |
| E2E | `web/tests/e2e/02-chat.spec.ts` | two-tab test scoped to the thread (see below) |

## How a conversation gets into the rail

1. `/chat` keeps a **conversation id** (`threadId`, a UUID) in the tab's
   saved thread. A new one is minted on first load, on "New chat", and on
   every landing-page hand-off (`?q=`), which is what makes each prompt
   chip a separate entry.
2. **After every completed run** (a `data-run` part appears), the page
   builds a compact transcript itself — `Q: …` / `A: …` lines, each
   capped at 300 chars, whole thing ≤ 2048 — titled by the first question,
   and `POST /api/chats` it. No model call; the backend only embeds it.
   A restored thread is not re-saved (`savedRunsRef` tracks how many runs
   were already saved).
3. The backend **upserts by (user, thread_id)**: a follow-up in the same
   conversation refreshes the same row (title, summary, embedding,
   `updated_at`) instead of adding a second entry.
4. The rail fetches on mount, so when the user navigates back to `/` the
   chat they just had is already there. On `/chat` it refetches after each
   successful save (`chatsVersion`), so the entry appears the moment the
   answer ends.
5. Because the rows are embedded, the agent's existing `recall_episodes`
   tool now actually has something to find — previously the table was
   always empty.

Ordering is by `updated_at` desc, so continuing an old chat moves it to
the top. Delete = deactivate (`active=false`): gone from the rail and from
`recall_episodes`, row kept. Everything else about the rail (hover ⋯, red
Delete, optimistic removal + rollback, drag-to-resize, 12 px heading,
hidden under 860 px, on both pages) is unchanged.

## Notes and decisions

- The rail lists conversations; it does not (yet) **reopen** one — the
  store holds a summary, not the transcript. Clicking an entry is the
  obvious next step and would need the messages saved too.
- The rail is **per user, not per tab** (unlike the thread itself). The
  existing "a second tab is its own conversation" test asserted on the
  whole `<body>` and started failing because the rail correctly listed
  both tabs' chats; it now checks the thread area only
  (`data-testid="thread"`).
- BFF rate limits: the list is fetched on every page load and after every
  run, so it has its own bucket (`chats-list`, 240/min) separate from
  saves and deletes (60/min). The spec uses a fresh user per test so tests
  share neither history nor buckets — the first run hit 429s because they
  did.
- The `/memory` endpoints (backend + `/api/memory` BFF) from Part 1 are
  still there and tested; they are just no longer surfaced in the UI.
- `POST /episodes` costs one OpenAI embedding call per completed run
  (`text-embedding-3-small`, on ≤ 2 KB of text).

## Verification

- `python -c "import harness.api.app"` OK; `pytest tests/unit` → **18 passed**.
- `tsc --noEmit`, ESLint clean; `next build` OK.
- `07-chats.spec.ts` → 7 passed (run twice for stability); with
  `02-chat.spec.ts` → **17 passed**. Full suite → 47 passed after the
  two-tab fix.
- Screenshot-verified: after Draft a note, Check the web and a typed
  question, the landing page lists all three, newest first, with times.

---

# Part 10 — Descriptions, "View all" history, and sort-by-date

Three additions to the Chats rail, all built on the existing `.h-*`
surfaces (`.h-popover`, `.h-btn-ghost`, `.h-chip`, `.h-scrim`/`.h-dialog`,
`.h-input`) and tokens, so light and dark both work.

| Layer | File | Change |
|---|---|---|
| API | `src/harness/api/routes/episodes.py` | `GET /episodes` items gain `preview` (one line, derived) and `summary` (the transcript) |
| Tests | `tests/unit/test_episode_routes.py` | preview derivation + field set |
| UI | `web/components/hangul/ChatsPanel.tsx` | description line; hover-revealed header actions; `HistoryDialog`; date filter menu |
| UI | `web/app/globals.css` | `.h-sidebar-actions`, `.h-tip`, `.h-menu-item`, `.h-clamp-2`, `.h-dialog-wide` |
| E2E | `web/tests/e2e/fake-backend.mjs`, `helpers.ts` | `preview`/`summary` in the stand-in; `POST /__episode` + `seedChat()` to plant a dated chat |
| E2E | `web/tests/e2e/07-chats.spec.ts` | 3 new tests (10 total) |

## 1. What each chat was about

Every row now shows, under the title, a one-line description clamped to
two lines (`.h-clamp-2`), then the time (`today · 11:20 AM`,
`yesterday · 3:20 PM`, else `Sep 10`). The description is `preview`,
derived on the backend from the stored transcript: the **first answer**
(whitespace collapsed, ≤ 160 chars, `…` if cut), falling back to the first
question. No extra model call and no schema change — it is computed from
`summary` at read time.

## 2. "View all" → the full history

Hovering the rail header reveals three small actions on the right
(`.h-sidebar-actions`, opacity 0 → 1 on `.h-sidebar-head:hover`, and kept
visible while one is focused or its menu is open):

- ↻ **Refresh**
- → **View all** — a themed tooltip (`.h-tip`, from `data-tip`, in
  `--solid-bg`/`--solid-fg`) says "View all" on hover.
- ⚙ **Sort by date** (see 3).

Clicking → opens `HistoryDialog`: the sign-in modal's scrim and dialog,
widened and left-aligned (`.h-dialog-wide`, 640 px), titled **All chats**
with the count. Each conversation is a card with its title, when, and the
**whole transcript** the rail stored — `you` / `ai` rows from the `Q:`/`A:`
lines of `summary` (the `you` lines in `--fg`, the `ai` lines in
`--muted`). Scrolls inside (`70vh`), closes on ✕, Escape, or a click on
the scrim. It respects the active date filter.

## 3. Sort by date

The ⚙ button opens a `.h-popover` menu headed **Sort by date** with three
`menuitemradio` entries:

- **Today** — chats last touched today
- **Yesterday**
- **Custom date** — reveals an `<input type="date">` (`.h-input`,
  `max` = today); the list follows the chosen day

Days are compared on the *local* calendar date of `updated_at`. While a
filter is active: the header count is the filtered count, a small chip
under the header names the filter (`Today` / `Yesterday` / `Jan 5, 2026`)
and clears it on click, the menu gains **Show all dates**, and an empty
result says "No chats on …" instead of "No chats yet".

## Verification

- `pytest tests/unit` → **19 passed**.
- `tsc --noEmit`, ESLint clean; `next build` OK.
- `07-chats.spec.ts` → **10 passed** (new: description shown and clamped;
  header actions hidden until hover, tooltip text is "View all", dialog
  lists every chat with its transcript lines, Escape closes; Today /
  Yesterday / Custom date each narrow to the right seeded chat, an empty
  day reports "No chats on", the dialog respects the filter, the chip
  clears it).
- `02-chat`, `01-auth-gate`, `05-upload` → 17 of 18; the one failure,
  `05-upload › upload after the session expired opens the sign-in modal`,
  passed on 6 of 7 re-runs. Its own comment describes a race between the
  session refetch and the upload's 401; the rail makes no request after
  the cookies are cleared in that test, so it is pre-existing flakiness,
  not caused here.
- Screenshot-verified in dark mode: descriptions under titles; hover shows
  ↻ → ⚙ with the "View all" tooltip; the Sort by date menu; the All chats
  dialog with transcripts.

---

# Part 11 — The chat box wraps and grows instead of scrolling sideways

| File | Change |
|---|---|
| `web/app/page.tsx` | landing composer: `<input>` → auto-growing `<textarea>`; `alignItems: "flex-end"` on the box; `MAX_COMPOSER_PX` |
| `web/app/chat/page.tsx` | same growth cap (`MAX_COMPOSER_PX = 200`, was 160), `overflow-x: hidden`, `data-testid="chat-composer"` |
| `web/tests/e2e/08-composer.spec.ts` | **new**, 3 tests |

## The problem

The landing page's composer was a single-line `<input>`, so a long
question scrolled horizontally inside one line. `/chat` already used a
`<textarea>` that grows, but its cap (160 px) was different from what the
landing page now gets.

## The fix

Both pages now use the same composer behaviour:

- A `<textarea rows={1}>` that **wraps** at the box's width
  (`overflow-x: hidden`, `white-space: pre-wrap` as textareas do) and, on
  every input, sets its own height to its `scrollHeight` — so as one line
  fills, the box grows by one line (22 px) and the cursor continues on the
  next, exactly like the box being typed into here.
- Growth is capped at **200 px** (~8 lines) on both pages; past that the
  box scrolls vertically (`overflow-y: auto`) instead of pushing the page.
- **Enter sends, Shift+Enter inserts a newline** (the landing page used to
  send on any Enter).
- The + (attach) and ↑ (send) buttons are aligned to the *bottom* of the
  box (`alignItems: "flex-end"`), so they stay put beside the last line as
  the box grows — same as `/chat`.

Everything else about the landing composer is unchanged: same
`.h-surface` box, same placeholder logic, same `onSubmit` → `/chat?q=`.

## Verification

- `tsc --noEmit`, ESLint clean; `next build` OK.
- `08-composer.spec.ts`: on `/` and on `/chat`, typing a ~230-character
  question makes the box more than twice its one-line height, leaves
  nothing to scroll horizontally, and keeps the full text; Shift+Enter
  adds lines and the height stops at ≤ 200 px with vertical scroll; Enter
  still sends on both pages. → **3 passed**; with `01-auth-gate` and
  `02-chat` (which type into both composers) → **17 passed**.
- Screenshot-verified: a five-line question wrapped inside the landing
  box, + and ↑ anchored beside the last line.

---

# Part 12 — Wider landing box; rail rows show the query only

| File | Change |
|---|---|
| `web/app/page.tsx` | composer container `maxWidth` 460 → **640** (`data-testid="landing-composer-box"`) |
| `web/components/hangul/ChatsPanel.tsx` | rail rows drop the answer line; title gets `data-testid="chats-title"` |
| `web/app/globals.css` | `.h-clamp-2` removed (no longer used) |
| `web/tests/e2e/08-composer.spec.ts` | width test |
| `web/tests/e2e/07-chats.spec.ts` | "description" test replaced by "query only, cut with …" |

### Wider chat box on the landing page

The landing composer was capped at 460 px (the `/chat` one is 720 px),
which read as narrow once it could hold several lines. It is now 640 px:
still centred in the space beside the rail, still shrinks with the
viewport (`width: 100%`). Nothing else about it changed.

### Rail rows: the user's query, nothing else

Part 10 had put the model's first answer under each title. Reverted per
feedback: each row is now **only the query** on one line, cut with `…`
when it does not fit (`white-space: nowrap; text-overflow: ellipsis`),
with the full text in the row's tooltip, and the time underneath. No model
text appears in the rail. The full `you`/`ai` transcript is still
available through **View all**, and the API still returns `preview`
(unused by the rail now, harmless to keep for the history view or a
future hover card).

### Verification

- `tsc --noEmit`, ESLint clean; `next build` OK.
- `08-composer.spec.ts` (+ width test) with `01-auth-gate` → **8 passed**.
- `07-chats.spec.ts` → **10 passed**; the new test asks a 100-character
  question and checks the row holds the full text, is drawn on one line
  with an ellipsis (`scrollWidth > clientWidth`), and contains no
  "Reply to" and no preview element.
- Screenshot-verified: three rows, the long one cut with "…", no answer
  lines; landing box visibly wider with a two-line question in it.

---

# Part 13 — The agent's activity folds into one line

| File | Change |
|---|---|
| `web/components/agent-activity.tsx` | new `ActivityGroup` (+ `ActivityItem`, `summarise`) beside the existing `ToolRow` |
| `web/app/chat/page.tsx` | `renderParts` groups each assistant message's tool/thinking parts into blocks; old `Thinking` component removed |
| `web/app/globals.css` | `.h-activity*`, `.h-sigil-live` + `@keyframes h-breathe`, `.h-shimmer` + `@keyframes h-shimmer`, reduced-motion fallback |
| `web/tests/e2e/09-activity.spec.ts` | **new**, 3 tests |

## The problem

Every step of a run — "Thinking…", "Searching your documents", "Read a
file", the next "Thinking…" — was rendered as its own row, so a run with
several tool calls pushed the thread down a line at a time, and the rows
stayed there afterwards.

## What it does now

Each unbroken stretch of activity between pieces of answer text is one
compact block (`ActivityGroup`), the way a chat UI keeps its working
state out of the way:

- **While working** — a single pill: the Hangul **sigil breathing**
  (`.h-sigil-live`, scale + glow in `--sigil`) and the *current* step in
  **shimmering text** (`.h-shimmer`, a `--muted` → `--fg` gradient sweeping
  through the label): "Thinking… step 1", then "Searching your documents
  *rollout plan*", then "Thinking about the next step… step 2". Earlier
  steps are folded under it, not listed.
- **When done** — the pill becomes a one-line summary of the whole run:
  "Searched your documents, read a file · 3 steps · 2.4s" (distinct
  finished labels, joined; step count; total tool time), with a still
  sigil and a chevron.
- **Expand on demand** — clicking the line unfolds the individual
  `ToolRow`s (unchanged: status tick, detail, timing, result preview) and
  clicking again folds them. Folded is the default.
- **Never hides what needs you** — a block unfolds itself when a row is
  `awaiting` approval, is an `error`, or is a file being *drafted* (its
  content streaming in), so the approval prompt and the live draft are
  still seen in full.
- Runs are separate: each answer's activity is its own block, so a long
  conversation is narration → block → answer, repeated, not a growing
  list of rows.
- `prefers-reduced-motion` turns both animations off.

The "Thinking…" before the first token (`showThinking`) is the same live
block with only a thinking item, so the indicator looks the same before
and during a run.

## Test compatibility

The existing specs were written against the rows; they still pass because
the block keeps their hooks: the summary line contains the done label
("Searched your documents"), the live header carries
`data-testid="thinking"` with the step number, and the auto-unfold keeps
`tool-row` / `tool-draft` in the DOM while a file is drafted or an action
awaits approval.

## Verification

- `tsc --noEmit`, ESLint clean; `next build` OK.
- `09-activity.spec.ts` → **3 passed**: live block has the animated sigil
  (`animation-name: h-breathe`), shimmer text and "step 1"; the finished
  block is single, folded, summarised, expands to one `done` row and folds
  again; an approval run unfolds itself; two runs give two folded blocks
  and zero visible rows.
- `02-chat`, `03-failures`, `04-approval` → 23 of 24; the one failure is
  the drafting-timing test already recorded as flaky in Part 3 (passed 2
  of 3 re-runs here, as before).
- Screenshot-verified in dark mode: "Thinking… step 1" pill with the
  sigil while waiting; after the answer a folded "Searched your documents
  · 42ms" line; expanded, the row beneath it.
