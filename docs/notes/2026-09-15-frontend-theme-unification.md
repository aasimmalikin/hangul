# Frontend: one theme for every page, profile menu, document upload (2026-09-15)

## Earlier state

- **Two visual systems.** The landing page (`web/app/page.tsx`) was hand-styled
  in the Hangul palette (`--bg`, `--fg`, `--surface`, `--solid-bg`, … set on
  `html[data-theme]`, Fraunces display type, antler sigil). The chat page
  (`web/app/chat/page.tsx`) was the stock Tailwind/shadcn look: white
  background, blue links, gray tool rows, amber/blue approval cards, a plain
  bordered textarea and a "Send" button. Signing in dropped the user from one
  design into a completely different one.
- **Theme tokens fought each other.** `globals.css` had *two* copies of the
  Hangul theme block (one with `--box-bg`, one with `--surface`), and the
  shadcn tokens (`--background`, `--secondary`, `--border`, …) still pointed at
  the default oklch greys with a `.dark` class variant nobody set — the app
  toggles `data-theme`, not a class. So anything built with Tailwind utility
  classes ignored the theme entirely.
- **Flash of wrong theme.** `ThemeProvider` set `data-theme` in a `useEffect`,
  so the first server paint had no theme variables at all. It also called
  `setState` synchronously inside an effect, which `npm run lint` rejected.
- **No profile UI.** The landing page showed the user's name and a bare
  "Sign out" text button; the chat page showed nothing about who was signed in
  and had no way to sign out.
- **No way to use the RAG pipeline from the UI.** The backend already had
  `POST /upload` (chunks + embeds a PDF/TXT/MD into the caller's
  `SessionVectorStore`, keyed by JWT `sub`, so `search_docs` finds it), but the
  Next.js app had no route for it and no button.
- **No sign-in gate on `/chat`.** The proxy (`web/proxy.ts`) only refreshes the
  session; it protects nothing. A signed-out visitor could open `/chat`, type
  a question, and get a silent 401 from `/api/chat`.

## What changed

### Theme system (`web/app/globals.css`)

- Collapsed the duplicated Hangul blocks into one per mode and added a few
  tokens that pages needed: `--surface-solid`, `--surface-hover`, `--faint`,
  `--bubble`, `--ok`, `--warn`, `--warn-bg`, `--err`, `--link`, `--scrim`.
- **Mapped the shadcn/Tailwind tokens onto the Hangul palette** under
  `html[data-theme="light"], html[data-theme="dark"]`. `bg-secondary`,
  `text-muted-foreground`, `border-border`, etc. now resolve to the same
  colours as the hand-styled pages, so the `ai-elements/` and `ui/`
  components follow the theme without edits. The `dark` custom variant now
  keys off `html[data-theme="dark"]` instead of a `.dark` class.
  - One collision worth knowing: shadcn's `--muted` is a *background*, Hangul's
    `--muted` is *text*. The Tailwind colour is pointed at `--bubble`
    (`--color-muted: var(--bubble)`) so `--muted` stays the text tone.
- Added reusable primitives in `@layer components` so new UI matches by
  construction — use these instead of ad-hoc styles:
  `.h-btn-solid` (primary), `.h-btn-outline`, `.h-btn-ghost`, `.h-icon-btn`
  (square, e.g. settings / +), `.h-icon-solid` (round send arrow),
  `.h-surface` (the input box), `.h-popover`, `.h-chip`, `.h-input`,
  `.h-scrim` + `.h-dialog` (modal), `.h-display` (Fraunces), `.h-muted`,
  and `.h-prose` for markdown inside assistant messages.

### Shared components (`web/components/hangul/`)

- `AppHeader` — the top bar every page uses: wordmark (optional), then either
  the signed-in avatar or Sign in / Sign up, then the theme gear.
- `ProfileMenu` — avatar (Google photo or initial) that opens a small menu
  with name/email and **Sign out**, which calls `signOut({ redirectTo: "/" })`
  so the user lands back on the landing page.
- `ThemeMenu` — the gear + light/dark toggle, extracted from the landing page.
- `SignInModal` — the one sign-in dialog (Google button, email magic link).
  Takes a `reason` line and a `callbackUrl`, so a page can say *why* it is
  asking and get the user back to where they were.
- `AttachMenu` — the **`+`** at the left of every composer (landing *and*
  chat). Clicking it opens a small menu; the only entry today is **Docs**,
  which opens the file chooser and posts the file to `/api/upload`. The
  sign-in gate lives inside it: a signed-out user never sees the menu, they
  get `onRequireSignIn("Sign in to add a document and ask questions about
  it.")` and the page opens its `SignInModal`. `placement="above" | "below"`
  picks which way the menu opens. New "add" options go here, as more menu
  items.
- `AttachmentChips` — the row of attached-document chips above a composer,
  with an "Indexing …" chip while an upload is in flight and an inline error
  if it fails.

### Pages

- `web/app/page.tsx` (landing) — same look, now built from `AppHeader`,
  `SignInModal` and the `.h-*` classes. The suggestion chips are buttons that
  submit their text. The input box has the **`+` / Docs** menu on the left,
  so a document can be added before the first question. The upload is
  indexed server-side immediately; when the question is submitted the
  document names ride along to `/chat?q=…&doc=<name>` so the chips carry
  over.
- `web/app/chat/page.tsx` — rebuilt in the Hangul theme:
  - Header with wordmark + profile menu + theme toggle.
  - Empty state uses the sigil and Fraunces title like the landing hero.
  - Composer is the landing input box: **`+` / Docs menu on the left**
    (`AttachMenu`), auto-growing textarea, round arrow-up send on the right.
  - Attached documents show as chips above the composer (`AttachmentChips`),
    seeded from any `?doc=` params handed over by the landing page.
  - Tool rows, choice cards and approval cards use theme tokens
    (`components/agent-activity.tsx` was recoloured too).
  - **Sign-in gate:** sending a message calls `requireAuth(reason)` and
    `AttachMenu` gates `+` itself; if there is no session the `SignInModal`
    opens with the matching reason.
    A `/chat?q=…` handed over from the landing page auto-sends for signed-in
    users and opens the gate for everyone else; the callback URL brings them
    back with `q` intact so it then sends.
  - `useSearchParams` is wrapped in `<Suspense>` as Next 16 requires for the
    static shell.

### Upload route (`web/app/api/upload/route.ts`)

BFF in the same shape as `/api/chat` and `/api/approve`: verify the NextAuth
session, mint a 5-minute service JWT, forward the multipart body to FastAPI
`POST /upload`, relay the JSON. The backend indexes the chunks under the
user's id, so the very next question can hit them via `search_docs`.

### Theme boot (`web/app/layout.tsx`, `web/components/ThemeProvider.tsx`)

- An inline `<script>` in `<head>` applies the saved theme to `<html>` before
  first paint (no flash); `<html>` carries `data-theme="dark"` as the SSR
  default with `suppressHydrationWarning`.
- `ThemeProvider` was rewritten on `useSyncExternalStore` — localStorage +
  `data-theme` are the source of truth, React subscribes to it, other tabs
  stay in sync via the `storage` event. This also cleared the lint error.

## How to add a page or button that matches

1. Wrap the page in `<main>` and put `<AppHeader onSignIn={…} />` at the top;
   own a `<SignInModal>` if the page has an action that needs a session.
2. Use the `.h-*` classes for buttons, inputs, surfaces and dialogs. Reach for
   `var(--fg)`, `var(--muted)`, `var(--surface)`, `var(--surface-border)`,
   `var(--solid-bg)` for anything custom. Never hard-code a colour.
3. Tailwind utilities are fine too (`bg-secondary`, `text-muted-foreground`,
   `border-border`) — they map to the same palette.
4. For markdown output, wrap it in `.h-prose`.

## Verification

- `npx tsc --noEmit`, `npm run lint`, `npm run build` all pass.
- Headless-browser screenshots of `/` and `/chat` in both themes, signed out
  (with the `+` gate on both pages) and with a mocked session + mocked stream
  (profile menu, user bubble, tool row, markdown, approval card,
  attached-document chip). Also walked the landing flow: `+` → Docs → file
  chooser → chip → question → `/chat?q=…&doc=handbook.pdf` with the chip
  still showing.
- Not exercised end-to-end here: a real Google/email sign-in and a real
  upload against the FastAPI backend (no backend running in this session).

## Files

| Path | Change |
| --- | --- |
| `web/app/globals.css` | theme consolidation, shadcn token mapping, `.h-*` primitives, `.h-prose` |
| `web/app/layout.tsx` | pre-hydration theme script, `data-theme` default |
| `web/components/ThemeProvider.tsx` | rewritten on `useSyncExternalStore` |
| `web/components/hangul/AppHeader.tsx` | new |
| `web/components/hangul/ProfileMenu.tsx` | new |
| `web/components/hangul/ThemeMenu.tsx` | new |
| `web/components/hangul/SignInModal.tsx` | new |
| `web/components/hangul/AttachMenu.tsx` | new — `+` button, Docs menu, upload, sign-in gate |
| `web/components/hangul/AttachmentChips.tsx` | new |
| `web/components/Wordmark.tsx` | dropped a stale `text-accent` class on the sigil |
| `web/components/agent-activity.tsx` | theme tokens instead of gray/green/red |
| `web/app/page.tsx` | rebuilt on shared components; `+` / Docs upload; hands `doc` names to `/chat` |
| `web/app/chat/page.tsx` | rebuilt in theme; `+` / Docs upload; sign-in gate; reads `?doc=` |
| `web/app/api/upload/route.ts` | new BFF → FastAPI `/upload` |

## Revision (same day)

Follow-up after review:

- The `+` was only on the chat composer; it is now on the landing page too,
  via the shared `AttachMenu`.
- `+` no longer opens the file chooser directly. It opens a menu with a
  **Docs** entry; choosing Docs opens the chooser. This leaves room for other
  "add" options later without changing the button.
- The menu entry is just "Docs" — no file-type / size hint under it.
- Documents attached on the landing page are carried to `/chat` as `?doc=`
  params so their chips persist across the hand-over.

## Revision 2: refresh wiped the conversation and re-sent the first message

### Symptom

Chat with the agent for a few turns on `/chat`, press refresh: every message
disappears except the first one, which is sent to the agent *again* and
answered again (costing a run).

### Root cause — two separate things

1. **Nothing persisted the thread.** `useChat()` keeps messages in React
   state only. The backend has no conversation store to reload from: the
   `threads` table was dropped (`alembic/versions/3b9593c85a81_drop_threads_table.py`),
   `api/routes/sessions.py` is empty, and `CheckpointStore` is keyed by
   *run id*, not by conversation. So a reload started from an empty thread.
2. **The hand-over URL was never cleaned up.** The landing page navigates to
   `/chat?q=<question>` and the chat page auto-sends `q` on mount, guarded
   only by a `useRef` — which is also reset by a reload. Because `q` stayed
   in the address bar, every refresh (and back/forward) looked like a fresh
   hand-over and sent the first question again. Combined with (1), the page
   showed *only* that re-sent message and its new answer.

### Fix (`web/app/chat/page.tsx`)

- **Persist the thread in the browser, per user.** After each completed
  turn the page writes `{ messages, resolved, attachments }` to
  `localStorage["hangul:chat:<user id>"]` (never while a stream is in
  flight). On mount, once the session is known, it restores that blob via
  `setMessages` — so messages, already-answered approval/choice cards, and
  the attached-document chips all come back. `resolved` is restored too;
  without it the "Approve / Reject" card would reappear with live buttons
  for a run that was already resumed.
- **Consume `q` once.** Right after `sendMessage({ text: q })` the page calls
  `router.replace("/chat")`, so the question is gone from the URL and a
  refresh cannot replay it.
- **"New chat" button** in the header (only shown once there are messages)
  clears the messages, resolved cards, attachments and the stored blob — the
  only way to start fresh now that history persists.

Helpers `loadThread` / `saveThread` / `clearThread` wrap `localStorage` in
`try/catch` (private mode, quota) and validate the shape before restoring.

### Trade-offs / known limits

- This is client-side persistence: the thread is per browser, not synced
  across devices, and the backend does not know about it. Each message is
  still sent to `/api/chat` on its own — the backend's memory/episodes tools
  are what give the agent continuity, not the UI history. Server-side
  threads would be the next step if cross-device history is wanted.
- One thread per user, not a list of past chats.

### Verification

Headless run with a mocked session and a mocked `/api/chat`:
land on `/chat?q=First+question` → URL becomes `/chat`, 1 API call; send a
second message → 2 calls, 4 bubbles; **reload → still 2 calls, all 4 bubbles
restored, URL still `/chat`**; New chat → reload → empty thread.
`tsc`, `eslint`, `next build` pass.

## Revision 3: "Continue with email" failed with `error=Configuration`

### Symptom

Google sign-in works. Entering an email and clicking **Continue with email**
lands on `/api/auth/error?error=Configuration` (HTTP 500). The dev server
logs:

```
[auth][error] Error: Resend error: {"statusCode":403,"name":"validation_error",
"message":"You can only send testing emails to your own email address
(aasimmallikk@gmail.com). To send emails to other recipients, please verify a
domain at resend.com/domains, and change the `from` address to an email using
this domain."}
```

### Root cause

Not a code bug — it is the mail provider's sandbox rule.

`web/.env.local` has `AUTH_EMAIL_FROM=onboarding@resend.dev`. That is Resend's
shared **test sender**, and a Resend account with no verified domain may only
send *to the account owner's own address*. So the magic link can be delivered
to `aasimmallikk@gmail.com` and to nobody else; any other recipient gets a
403 from Resend, `sendVerificationRequest` throws, and Auth.js reports the
throw as a `Configuration` error by redirecting to its bare error page.

The `pg` warning above it in the log (`sslmode=require` semantics changing)
is unrelated noise from the Neon connection string; see "Also" below.

### The real fix (Resend side — needs your action)

1. Add and verify a domain you own at <https://resend.com/domains> (DNS TXT
   / DKIM records).
2. Change the sender to that domain, e.g. in `web/.env.local`:
   ```
   AUTH_EMAIL_FROM="Hangul <login@yourdomain.com>"
   ```
3. Restart `next dev`. Any address can then receive the link.

Until then, email sign-in only works for the Resend account's own address.

### What changed in the app (`web/components/hangul/SignInModal.tsx`)

The failure is now handled *inside the modal* instead of throwing the user
onto Auth.js's unstyled error page:

- `signIn("resend", { email, redirectTo, redirect: false })` — with
  `redirect: false` the client gets `{ error, ok, url }` back instead of
  navigating. Auth.js encodes a failed send as `error: "Configuration"` and a
  successful one as a `/api/auth/verify-request` URL.
- **Error state:** the input turns red and a message under it explains that
  the link could not be sent to that address and suggests Google. Typing
  clears it. (The specific Resend reason stays in the server log; users
  don't need to see provider internals.)
- **Sent state:** the modal switches to "Check your inbox — we sent a
  sign-in link to *address*" with a "Use a different email" button, rather
  than visiting Auth.js's default verify-request page.
- Light client-side validation so an obviously malformed address never
  reaches Resend.

How the email flow works end to end now: modal → `POST
/api/auth/signin/resend` (Auth.js) → Resend sends a one-time link →
user opens it → Auth.js `callback/resend` verifies the token, creates/loads
the user via the Postgres adapter, sets the JWT session cookie, and redirects
to `redirectTo` (the page the modal was opened from). The `callbackUrl` prop
on `SignInModal` controls that landing page.

### Also: the `pg` SSL deprecation warning

`AUTH_PG_URL` ends in `?sslmode=require&channel_binding=require`. Newer
`pg` warns that `sslmode=require` will stop verifying certificates the way
libpq does. Harmless today; to silence it, append `&uselibpqcompat=true`
(keep libpq semantics) or switch to `sslmode=verify-full`. Not changed here
because it lives in `.env.local`.

### Verification

Headless run against the production build with Auth.js's endpoints mocked:
the `error=Configuration` response shows the inline error and stays on the
page; the `verify-request` response shows the "Check your inbox" state. A
real send to a non-owner address will keep failing until the domain is
verified; a send to `aasimmallikk@gmail.com` should succeed today.

## Revision 4: "Sign up" now opens a real sign-up flow with Google

### Before

The **Sign up** button in the header called the same handler as **Sign in**,
so it opened the "Sign in to continue" dialog with "Continue with Google".
Functionally it worked — Auth.js's Postgres adapter creates the `users` row
on the first Google callback, so sign-in *is* sign-up for a new account — but
nothing about it read as creating an account, and Google could silently pick
whichever account the browser already had cached.

### What changed

`web/components/hangul/SignInModal.tsx`

- New `mode?: "signin" | "signup"` prop (`AuthMode` is exported). A `COPY`
  table holds the words for each mode:
  - signin: "Sign in to continue" / "Continue with Google" / "Continue with email"
  - signup: "Create your account" / "Sign up with Google" / "Sign up with email"
  `title` and `reason` still override the copy when a page passes them.
- In signup mode the Google button calls
  `signIn("google", { redirectTo }, { prompt: "select_account" })`. The third
  argument is Auth.js's `authorizationParams`; `@auth/core` merges it into
  the Google authorization URL (`lib/actions/signin/authorization-url.js`),
  so Google always shows its account chooser for a sign-up instead of
  auto-selecting the cached session. Sign-in mode keeps the default so
  returning users are not asked every time.

`web/components/hangul/AppHeader.tsx`

- Takes an optional `onSignUp` alongside `onSignIn`; the **Sign up** button
  uses it, falling back to `onSignIn` if a page does not pass one.

`web/app/page.tsx`, `web/app/chat/page.tsx`

- The modal state now carries `mode`. Header **Sign in** → signin mode,
  **Sign up** → signup mode. Every gate (sending a message, `+` upload, the
  `?q=` hand-over) stays in signin mode with its own reason line.

### How the Google sign-up works end to end

1. **Sign up** → modal in signup mode → **Sign up with Google**.
2. Client `POST /api/auth/signin/google?prompt=select_account` → Auth.js
   builds the Google OAuth URL (with PKCE/state) and redirects the browser.
3. Google shows the account chooser, then consent (first time only), then
   redirects to `/api/auth/callback/google`.
4. Auth.js exchanges the code (through `resilientFetch`, see the ETIMEDOUT
   note), fetches the profile, and — via `@auth/pg-adapter` — inserts a row
   in `users` and a linked row in `accounts` if the email is new, or reuses
   the existing user if not. Then it sets the JWT session cookie and
   redirects to `redirectTo` (the page the modal was opened from).
5. The `session` callback in `auth.config.ts` copies `token.sub` (the
   integer `users.id`) onto `session.user.id`, which the BFF routes use to
   mint the FastAPI service token.

So "sign up" and "sign in" share one code path on the server; the only
differences are the copy and the `prompt=select_account` hint.

### Verification

Headless run against the production build with Auth.js's `providers`,
`csrf` and `signin/google` endpoints mocked: **Sign up** opens the
"Create your account" dialog, and clicking **Sign up with Google** sends
`POST /api/auth/signin/google?prompt=select_account`. `tsc`, `eslint` and
`next build` pass. A real Google round-trip was already confirmed working
by you earlier today.

## Revision 5: signing up with Google using an email that already had an account → server error

### Symptom

A user whose email is already in `users` (for example they first signed in
with the email magic link) clicks **Sign up** → **Sign up with Google** with
that same address. Google succeeds, but the callback ends on an Auth.js
error page: `/api/auth/error?error=OAuthAccountNotLinked`.

### Root cause

Auth.js's callback (`@auth/core/lib/actions/callback/handle-login.js`) looks
up the OAuth identity in `accounts`; there is no `google` row yet, so it
falls back to `getUserByEmail`. It finds the existing user but, by default,
refuses to attach a new OAuth identity to an existing user *unless* the
provider is marked as trusted for email linking — because a sloppy OAuth
provider could let someone sign in with an unverified email and hijack the
account. So it throws `OAuthAccountNotLinked` and redirects to its raw error
page, which in this app rendered as a server error.

Note the reverse direction (Google first, then the email link) already
worked: the email provider signs into whatever user owns the address.

### How this is handled in practice, and what changed

Real products (Vercel, Linear, Notion, GitHub, …) do **not** make the person
create a second account or bounce them to an error page. They treat a
*verified* email from a trusted identity provider as proof of the same
person and merge into the one account — while refusing unverified emails.
That is exactly what is implemented now:

`web/auth.config.ts`

1. `allowDangerousEmailAccountLinking: true` on the Google provider. On a
   Google sign-in whose email matches an existing user, Auth.js now links
   the Google identity to that user (`linkAccount` → new row in `accounts`)
   and signs them in. The user keeps their id, memory, ledger and episodes.
2. A `signIn` callback that only permits Google logins when
   `profile.email_verified === true`. Google sends this OIDC claim on every
   profile; it is the safety condition that makes step 1 acceptable — an
   unverified address can never claim an existing account. Denied sign-ins
   land on the error page with code `AccessDenied`.
3. `pages.error = "/auth/error"`, so any Auth.js failure redirects to our
   page instead of the framework's.

`web/app/auth/error/page.tsx` (new)

A themed page (AppHeader, sigil, Fraunces title) that maps Auth.js's error
codes to plain-language copy and a next step:

| code | shown as |
| --- | --- |
| `OAuthAccountNotLinked` | "That email is already registered" — sign in the way you did before, or use the email link; same account either way |
| `AccessDenied` | "We couldn't verify that account" — the provider hasn't verified the email |
| `Verification` | "That sign-in link has expired" |
| `Configuration` | "Sign-in isn't available right now" |
| anything else | "Something went wrong signing you in" |

Buttons: **Try signing in again** (opens the shared `SignInModal`) and
**Back to home**. The raw code is printed small at the bottom for support.

`OAuthAccountNotLinked` should no longer occur for Google after change 1;
the copy stays for any provider added later without linking enabled.

### Resulting behaviour

- Email-link first, then Google with the same address → signed into the
  same account, Google now linked; next time either method works.
- Google first, then email link → same account (already the case).
- "Sign up" with an address that already exists → simply signs in. There is
  no "account already exists" dead end; sign-up and sign-in converge, which
  is the norm for passwordless + social auth.
- Google account with an unverified email → refused with a clear message.

### Verification

- `tsc`, `eslint`, `next build` pass; `/auth/error` is a static route.
- Against the production build: `GET /api/auth/error?error=OAuthAccountNotLinked`
  returns `302 → /auth/error?error=OAuthAccountNotLinked`, and that page
  renders the "already registered" copy in the theme.
- The linking itself needs a real Google round-trip: sign in with the email
  link using an address, sign out, then **Sign up with Google** with the
  same Google address. Expect to land signed in, and a new `google` row in
  `accounts` pointing at the existing `users.id`.

## Revision 6: resilience under real-world use — scenarios, hardening, hidden features, and a test suite

### What the system was before this revision

Functionally complete for the happy path, fragile off it:

| Area | Earlier state |
| --- | --- |
| Frontend ↔ backend | `useChat` posted to the BFF and showed whatever came back. A dropped stream, a dead backend, an expired session or a 429 all looked the same: a spinner that stopped, or a raw error string. No retry, no offline indication. |
| Refresh / back-forward | Fixed in Revision 2 for the idle case only — a question sent right before navigating away was lost (thread saved only while idle). |
| Multiple tabs | A `storage` event from another tab *replaced* local state, so an older snapshot could undo an approval just made in this tab. |
| Offline | `SessionProvider` re-fetched `/api/auth/session` on focus; offline that fetch fails and next-auth reports "unauthenticated" — a network blip looked like a sign-out and opened the sign-in modal. The very first session fetch had the same weakness, and typing before it resolved opened the gate too. |
| BFF (`web/app/api/*`) | No timeouts (a hung backend hung the request for as long as the platform allowed), no origin check (cross-site POST with the user's cookie would work), no rate limit, no body validation (10 MB check only in the backend, malformed JSON became a 500), raw backend errors relayed as-is, 401 from the backend indistinguishable from a real sign-out. |
| Backend `/approve` | **Any signed-in user could approve/resume any run** — `threads` had no owner column. Two concurrent approves (double-click, retry) both executed the destructive tool. |
| Backend `/traces`, `/metrics` | Unauthenticated; traces carry every user's questions and tool arguments. |
| Backend limits | No cap on simultaneous runs per user; question length unbounded; `AskRequest.thread_id` accepted but ignored. |
| Backend stream | Client disconnect noticed only when the next event arrived — a closed tab kept paying for tokens through a long model call. |
| Conversation context | Every message was a fresh run: the agent never saw the previous turn. Follow-ups like "and the second one?" had no context except the episodic-memory tool. |
| Hidden features | The backend computed per-run cost/steps/tools (`done` event), had a documents-only mode (`docs_only`), memory tools (`remember`/`recall`/`recall_episodes`), an eval quality gate (`/quality`) and a health check — none of it reached the UI. |
| Tests | None. |

### Scenario matrix — what happens now

Each row is exercised by the e2e suite (`web/tests/e2e/`) or the backend unit tests (`tests/unit/test_resilience_backend.py`).

**Identity & access**

| Scenario | Behaviour |
| --- | --- |
| Signed-out user sends, presses `+`, or arrives via `/chat?q=` | Sign-in modal with the specific reason; nothing is sent (backend counter stays 0). |
| Types and hits Enter before the session is known | Session is now rendered on the server into `SessionProvider`, so there is no "loading" window; if one ever occurs the text is queued and sent the moment the session resolves. |
| Session cookie expires/revoked mid-conversation | Next send → BFF 401 `{code:"unauthorized"}` → modal "Your session has expired… your conversation is kept"; thread untouched. Same for an upload. |
| Backend rejects the *service* token (401 from FastAPI) | Not the user's fault: shown as a backend fault, no sign-in modal. |
| Cross-site POST with a valid cookie | 403 `forbidden_origin` (`Sec-Fetch-Site` / Origin-vs-Host check) before any work. |
| Anonymous call to any `/api/*` | 401 `{code:"unauthorized"}`. `/api/quality` included. |
| Two users at once | Each gets their own answer (`user=<id>` in the fake's reply), own thread (`sessionStorage` keyed by user id, per tab — see Revision 9), own backend slot. Bob on Alice's browser sees an empty thread, never hers. |
| Approve someone else's run | 404 (not 403 — the run's existence is not confirmed). Verified in `test_approve_by_other_user_is_not_found`. |
| Admin-only endpoints | `/traces`, `/metrics` now require the `admin` role. |

**Connectivity**

| Scenario | Behaviour |
| --- | --- |
| Browser goes offline | Banner "You're offline…", Send disabled, no session refetch (`refetchWhenOffline=false`) so the header keeps showing the avatar. Back online → banner clears, sending works. |
| Backend down (503 / connection refused / DNS) | BFF answers 502 `upstream_unreachable` within its timeout; notice card with Retry; banner "The assistant is unreachable… retrying" polling `/api/health` every 10 s (60 s when healthy), plus "Check now". |
| Backend hangs mid-answer | BFF idle watchdog (120 s without any byte, heartbeats count) cancels and sends "The assistant stopped responding"; absolute cap 290 s. Partial text is kept. |
| Stream cut by the server mid-answer | BFF notices the stream ended without `done`/`error` → error event "connection … interrupted"; partial text kept; Retry re-sends the same question (`regenerate`). |
| Agent raises | Backend `error` event is relayed verbatim into a notice, not swallowed. |
| Backend 500 / 429 / 422 | Relayed as `{detail, code}` with the backend's own message; 429 keeps `Retry-After`. |
| User closes the tab / navigates away mid-answer | BFF cancels the upstream body → backend `request.is_disconnected()` (now polled every second even while the model is quiet) → run cancelled, no more tokens billed. |
| Back → forward, or navigate away and return, mid-answer | Thread is saved on every change now, so the question (and any streamed text) is restored. If no reply at all had arrived, a "didn't get an answer" notice offers Retry; a reply that did arrive is shown as-is (see Revision 8). |
| Refresh | Thread restored; `?q=` was consumed on first send so nothing re-sends (Revision 2), verified again here. |
| Rate limited | BFF: 60 chat / 10 upload / 30 approve per user per minute → 429 with `Retry-After`. Backend: max 3 runs in flight per user → 429. |

**Human-in-the-loop**

| Scenario | Behaviour |
| --- | --- |
| Approve a destructive tool, double-click | One execution. `CheckpointStore.claim_pending` is a single conditional `UPDATE … WHERE thread_id=? AND user_id=? AND pending_tool IS NOT NULL` (`FOR UPDATE SKIP LOCKED`), so exactly one caller wins; the UI also disables the buttons while busy. |
| A stale approve (old card, retried request) | 404 "already handled" from the backend's atomic claim; never a second run. (Tabs no longer share a thread — Revision 9.) |
| Card survives a refresh | Persisted with the thread; still decidable. |
| Clarifying question (`ask_user`) | Options rendered; choice resumes the run. |

**Documents**

| Scenario | Behaviour |
| --- | --- |
| Wrong type / >10 MB / empty file | Refused by the BFF with a clear message; never reaches the backend. |
| Upload times out | 110 s cap → "The upload timed out. Try a smaller file." |
| Upload from the landing page | Indexed immediately; chip carried to `/chat` via `?doc=`. |

**Input bounds** — question ≤ 8 000 chars (textarea `maxLength`, BFF and backend all enforce), history ≤ 20 turns × 4 000 chars, `history[].role` ∈ {user, assistant} (a `system` entry is rejected — prompt injection through history is not possible), approval id `^[\w-]{1,64}$`, decision ∈ {approve, reject}.

### Changes, by layer

**Backend (`src/harness`)**

- `alembic/versions/7a1c2e9d4b10_add_user_id_to_threads.py` — `threads.user_id` (indexed). **Run `alembic upgrade head`.**
- `checkpoint/checkpoint.py`, `checkpoint/store.py` — `Checkpoint.user_id`; `claim_pending(thread_id, user_id)` (atomic ownership check + take); `save` never blanks an owner.
- `agent/loop.py` — `run_agent(..., user_id=, history=)`: stamps the owner on the checkpoint; seeds `history` between the system prompt and the new question on a fresh run.
- `api/routes/ask.py` — `AskRequest.history: list[HistoryMessage]` with bounds; `question` max length; history and `docs_only` flow into the cache key (`cache/keys.py`) and into `run_agent`; `/ask` wrapped in `run_slot`.
- `api/routes/ask_stream.py` — `run_slot` per user; disconnect polled with a 1 s `wait_for` so cancellation happens during quiet periods.
- `api/routes/approve.py` — `claim_pending` instead of `load`; `decision` validated; owner passed to `run_agent`.
- `api/concurrency.py` (new) — `run_slot()` async context manager, `MAX_IN_FLIGHT_PER_USER = 3`, 429 + `Retry-After`. Per process; note in the docstring on how to make it exact across replicas.
- `api/routes/observability.py` — router-level `require_admin`.

**BFF (`web/app/api`, `web/lib`)**

- `lib/bff.ts` (new) — `assertSameOrigin`, `requireUser`, `rateLimit`, `upstream()` (service token + `AbortSignal.timeout` + `AbortSignal.any` with the client's signal), `relayUpstreamError` (backend status → stable `code`), `jsonError`. Every route uses the same four steps.
- `lib/service-token.ts` — `jti` claim so the backend's revocation list can target one token.
- `api/chat/route.ts` — validation; builds `history` from the transcript; forwards `docs_only`; idle watchdog + total cap; `done` → `data-run` part; end-of-stream without `done` → error event; `cancel()` propagates client disconnect upstream; `X-Accel-Buffering: no`.
- `api/approve/route.ts`, `api/upload/route.ts` — same guards; upload validates type/size/emptiness and sanitises the file name.
- `api/health/route.ts` (new) — up/down of the backend, unauthenticated, no-store.
- `api/quality/route.ts` (new) — session-gated relay of `/quality`, 60 s private cache.
- `next.config.ts` — CSP (`frame-ancestors 'none'`, `connect-src 'self'`, Google avatars allowed), `nosniff`, `X-Frame-Options: DENY`, referrer and permissions policies.

**Frontend (`web/app`, `web/components`)**

- `components/hangul/useConnectivity.ts` (new) — `navigator.onLine` via `useSyncExternalStore` + `/api/health` polling; re-checks on `online`, tab focus and bfcache `pageshow`.
- `components/hangul/StatusBanner.tsx` (new) — offline / backend-unreachable line with "Check now".
- `lib/apiError.ts` (new) — normalises AI-SDK errors and `Response`s into `{code, detail}`.
- `components/Providers.tsx`, `app/layout.tsx` — session resolved with `auth()` on the server and passed to `SessionProvider`; `refetchWhenOffline={false}`. (Pages are now server-rendered per request rather than static — expected for an authenticated app.)
- `app/chat/page.tsx` — `onError` → `handleFailure` (401 → modal, unreachable → recheck, else notice); notice card with **Retry** (`regenerate`) and Dismiss; **Stop** button while streaming; **Documents only** toggle (sent as `docsOnly`); `RunFooter` from `data-run` (steps · tools · time · cost); save on every change; "cut short" detection via missing `data-run`; cross-tab merge instead of replace; queued send while session loading; offline never opens the sign-in gate; approve 404 → "already handled".
- `components/hangul/AttachMenu.tsx` — upload 401 → sign-in modal; 120 s timeout with its own message.
- `components/hangul/ProfileMenu.tsx` — **Answer quality** row (correctness / faithfulness / gate verdict / cases) from `/api/quality`.
- `components/agent-activity.tsx` — labels for `remember`, `recall`, `recall_episodes`.

**Backend features now visible to the user**

| Backend feature | Where it shows |
| --- | --- |
| Per-run cost, steps, tools, duration (`done` event, ledger) | footer under every answer |
| `docs_only` mode (search_docs only, "I couldn't find that in your document") | "Documents only" toggle in the composer |
| Memory tools (`remember`, `recall`, `recall_episodes`) | named tool rows ("Saved to memory", "Looked at past conversations") |
| Eval quality gate (`/quality`) | "Answer quality" in the account menu |
| Health check (`/healthz`) | status banner |
| Conversation history (`AskRequest.history`, new) | follow-ups just work |

**Tests**

- `tests/unit/test_resilience_backend.py` — 7 tests with fakes (no DB, no model): owner-only approve, double-approve executes once, foreign run → 404, bad decision → 422, in-flight cap, request bounds, history reaches the model & owner stamped, cache key covers history/mode/user.
- `web/tests/e2e/` — 37 Playwright tests in six files (auth gate, conversation, failures, human-in-the-loop, documents, security & concurrency) against the production build, a real Auth.js JWT cookie (`helpers.signInAs`), and `fake-backend.mjs` (a scriptable FastAPI stand-in). `npm run test:e2e`.

### What would still break, and what to do then

- **Several server instances.** BFF rate limits and the backend in-flight cap are per process (bounded, not exact). Move both to Redis counters when scaling out. The uploaded-document index (`SessionVectorStore`) is also per process — already noted in CLAUDE.md.
- **Cross-device history.** The thread is per browser. Server-side threads (a `conversations` table keyed by user) would give history everywhere; the `history` plumbing added here is the same shape a server store would feed.
- **Resuming a stream after a drop.** The backend keeps the checkpoint but has no "reconnect to run X" endpoint; today the user retries the question. Adding `GET /ask/stream/{run_id}` + AI SDK `resume` would make a network drop invisible.
- **`allowDangerousEmailAccountLinking`** (Revision 5) stays safe only while the `signIn` callback keeps requiring `email_verified`. Don't remove one without the other.

### Verification

- `pytest tests/unit` → 7 passed. `ruff check src/` → 82 findings (was 83; none new).
- `tsc`, `eslint`, `next build` clean.
- `npx playwright test` → 37 passed, twice in a row.

## Revision 7: every request answered "token revoked"

### Symptom

After Revision 6, every call from the UI to the backend failed with
`401 token revoked`.

### Root cause

Revision 6 added a `jti` claim to the service token (`web/lib/service-token.ts`)
so the backend could revoke a single token. That switched on a code path in
`src/harness/auth/revocation.py` that had never run before — `api/auth.py`
only checks revocation when the token has a `jti`, and until now none did.
That path had three bugs:

1. `get_redis.get(...)` — `.get` was called on the factory *function* instead
   of the Redis client it returns → `AttributeError` on every call.
2. A bare `except:` turned that error into `return True` — "revoked".
3. `is_revoked` didn't `return` its comparison anyway, and `revoke()` had the
   same `get_redis.` mistake plus `exp=` where redis-py takes `ex=`.

So the moment tokens carried a `jti`, every one of them was rejected.

### Fix (`src/harness/auth/revocation.py`)

- Call `get_redis()`; return the comparison; `ex=` for the TTL.
- **Fail open, loudly.** Revocation is a secondary control on a token that
  expires in five minutes; the signature and expiry checks in `api/auth.py`
  remain strict. If Redis is unreachable the check now logs a warning and
  allows the token instead of locking every user out because a cache is down.
- `tests/unit/test_revocation.py`: fresh token allowed, revoked token
  rejected, other tokens unaffected, Redis outage allows.

No restart of the frontend is needed; restart `uvicorn` to pick up the fix.

## Revision 8: "That answer was cut short." showed on normal responses — removed

### What it was

Revision 6 added a heuristic: every completed run ends with a `data-run`
footer (steps · tools · time · cost), so an assistant reply *without* one was
treated as interrupted and got a red "That answer was cut short." card with a
Retry button.

### Why it was wrong

The absence of the footer is not proof of a broken answer. Threads saved
before Revision 6 have no footers at all; any answer path that does not end
in the streaming route's `done` event (an approval resumed through
`/approve`, a legacy thread, a future event change) also lacks one. The card
then appeared under perfectly good responses.

### Change (`web/app/chat/page.tsx`)

The `data-run` rule is gone. The interrupted notice now appears only when:

- the request itself failed (an explicit error from the stream or the BFF), or
- the last message is the user's question and **no** reply arrived at all
  (navigated away before the first token, request never went out).

A reply that arrived is shown as-is. The `data-run` footer is still rendered
when present; it just no longer judges the answer.

E2E specs 02 and 03 re-run green (16 tests).

## Revision 9: one conversation per tab; no cost/steps footer

### Before

- The thread was stored in `localStorage` under the user's id and synced
  between tabs through `storage` events. Opening `/chat` in a second tab
  showed the same messages, and a question asked in one tab appeared in the
  other. That is one conversation shared across tabs — not what the user
  wants: a new tab should be a fresh chat, and two tabs must never mix.
- Every answer carried a footer: "2 steps · search docs · 4.1s · $0.0021".

### Changes (`web/app/chat/page.tsx`)

- **Per-tab threads.** The thread now lives in `sessionStorage`, which the
  browser scopes to the tab: refresh, back and forward inside that tab
  restore it; a new tab starts empty; tabs cannot see each other. The
  cross-tab `storage` sync (and its merge logic) is removed. The key is still
  `hangul:chat:<user id>` so signing in as someone else in the same tab never
  shows the previous user's thread. Any old `localStorage` copy is deleted on
  first load.
  - Browser note: "Duplicate tab" and ctrl/cmd-click from a same-origin link
    copy `sessionStorage` (browser behaviour), so those start with a copy of
    the thread; from then on they are independent. A tab opened by typing the
    URL or from a bookmark starts clean.
- **No run footer.** The `data-run` part still travels with the message (it
  marks the end of a run and carries steps/cost for the record) but renders
  as a hidden marker; nothing about steps, tools, duration or dollars is
  shown under answers. The per-run cost is still recorded in the backend
  ledger and visible to operators through `/metrics` and `/traces`.

### Tests updated

- "a second tab is its own conversation" replaces the shared-thread test:
  tab 2 starts empty, each tab keeps its own thread across its own refresh,
  neither shows the other's messages.
- The two-tab approval test is replaced by "an approval already handled is
  refused": the backend's atomic claim still guarantees one execution.
- `expectReply` waits for the hidden `run-done` marker instead of the footer.
- Full suite: 37 passed.

## Revision 10: see what the agent is doing, and what it wants to write, before approving

### Symptom

Asking the agent to save a file gave a blank "Thinking…" for the whole
model call, then everything at once: a tool row reading **"✓ Wrote a file"**
(nothing had been written) and a bare card "The assistant wants to run
`filesystem__write_file`. Allow it?" with no sign of *what* it would write.

### Root causes

1. **The backend only announced a tool call after the model had finished
   generating it.** `OpenAIProvider.chat_stream` collected the tool-call
   fragments silently and yielded them only in the final `AssistantTurn`, so
   for a write-file turn — which has no narration text — the stream carried
   nothing until `tool_call` arrived complete. The UI had nothing to show.
2. The loop emits a placeholder `tool_result` (`ok: true`, preview
   "Waiting for your approval.") for the parked call so the message history
   stays valid. The BFF turned any `ok` result into status `done`, hence the
   tick and "Wrote a file".
3. The approval card printed the tool id only; the arguments (path, content)
   were in the event but never rendered.

### Changes

**Backend**

- `providers/openai_provider.py` — `chat_stream` now also yields
  `("tool_start", {id, name})` the moment a tool call's name appears in the
  delta stream, and `("tool_args", {id, delta})` for every fragment of its
  JSON arguments.
- `agent/loop.py` — forwards those as `tool_pending {id, name, step}` and
  `tool_args_delta {id, text}` events (documented in the `run_agent`
  docstring next to the others).
- `api/routes/ask_stream.py` — both added to `AGENT_EVENTS`.

**BFF (`web/app/api/chat/route.ts`)**

- `step` → `data-status` part (fixed id `status`, `{phase:"thinking", step}`);
  cleared to `idle` at the first text, tool, approval, done or error. So the
  page can say "Thinking… step 2" instead of nothing.
- `tool_pending` → `data-tool` part with status `pending`.
- `tool_args_delta` → the raw JSON so far is run through the AI SDK's
  `parsePartialJson` and the partial object is pushed into the same part —
  the user watches `content` grow.
- `tool_result` whose preview says *awaiting approval* → status `awaiting`;
  "not run — earlier call needs approval" → `skipped`. Neither is `done`.

**Frontend**

- `components/agent-activity.tsx` — statuses `pending | running | done |
  error | awaiting | skipped` with per-tool wording ("Drafting a file" →
  "Wants to write a file · needs your approval" → "Wrote a file"). While
  pending, the long argument (a file's `content`, or `edits`) streams in a
  monospace block under the row with a cursor.
- `app/chat/page.tsx` — `data-status` renders the thinking indicator inline
  (with the step number) only while the run is live. The approval card is
  now **"Approve this action?"** with the file name, its full path, the
  complete content in a scrollable block ("Content to write · N
  characters"), edits as −/+ pairs, any other arguments as a key/value list,
  and the line "Nothing has been changed yet. The agent will only continue
  once you decide." above Approve / Reject. Same warm-tone card, same tokens.
- Stop button icon fixed (`ti-player-stop`; the "-filled" glyph does not
  exist in this Tabler build, which is why the button was a blank circle).
- A stopped run that produced nothing readable offers Retry again (an
  assistant turn with no text/approval/question is treated as unanswered —
  distinct from the footer heuristic removed in Revision 8).

### Verified

- Raw SSE from the real backend for "create a file": `step → tool_pending →
  tool_args_delta… → tool_call → tool_result(awaiting) → approval_required →
  done`.
- Real UI, real model: "Drafting a file · autumn.txt" with the poem appearing
  line by line, then the card with path, full content and the buttons.
  (The card lands a couple of seconds after the row turns to "needs your
  approval": the loop awaits the checkpoint write to the remote Postgres
  before it can hand out the approval id.)
- Fake backend now streams the call the same way; e2e suite 39 passed.
