# Google sign-in worked, but chat/profile never loaded (2026-09-15)

## Symptom

- "Continue with Google" completed. A row appeared in `users` (id 3, my email)
  and a linked row in `accounts` (provider `google`).
- After that, nothing: the profile never loaded and I could not chat with the
  agent.

## Root cause

Three separate things, all introduced by the move to the Auth.js Postgres
adapter (`@auth/pg-adapter`) + JWT sessions.

### 1. Backend wanted an integer user id, frontend sent an email

The new schema (`alembic/versions/19ab5ed5598c_initial_schema.py`,
`src/harness/db/models.py`) changed `user_id` on `user_memory`,
`transactions`, and the new `episodes` table from `String(64)` to `Integer`
(a foreign reference to `users.id`).

But the Next.js BFF still minted the FastAPI service token with the email:

```ts
// web/app/api/chat/route.ts (before)
const token = await mintServiceToken(session.user.email, "user")
```

FastAPI takes `sub` as `user_id`, and the very first DB call in
`_build_and_run` is `profile_text(user_id)` (`src/harness/db/memory.py`).
Postgres rejected it:

```
psycopg.errors.UndefinedFunction: operator does not exist: integer = character varying
```

That exception killed the run before the agent even called the model, which is
what looked like "profile not loading".

### 2. The session never exposed the id

With `session: { strategy: "jwt" }`, Auth.js stores `users.id` in the token's
`sub`, but the default `session` object only carries `name`, `email`, `image`.
So the BFF had no id to send even if it wanted to.

### 3. Landing page never navigated to `/chat`

`onSubmit` in `web/app/page.tsx` always opened the "Sign in to continue" modal,
even when `useSession()` reported `authenticated`. Nothing routed to `/chat`.

## Fix

| File | Change |
|---|---|
| `web/auth.config.ts` | Added `callbacks.session` that copies `token.sub` -> `session.user.id`. |
| `web/app/api/chat/route.ts`, `web/app/api/approve/route.ts` | Gate on `session.user.id` and mint the service token with it instead of the email. |
| `src/harness/db/memory.py`, `ledger.py`, `episodes.py` | Cast `user_id` to `int` at the DB boundary. |
| `web/app/page.tsx` | Signed-in users go to `/chat?q=<question>` on submit; only signed-out users see the modal. |

Why cast in the DB layer instead of in `get_current_user`: a JWT `sub` is
always a string, and the same `user_id` is used *as a string* for
`data/sessions/<user_id>` and for the Redis cache key. Casting only where the
value meets Postgres was the least invasive option. Note that psycopg does
**not** coerce `"3"` to an integer on its own; `profile_text("3")` failed the
same way before the cast.

## How it was verified

1. Reproduced: `profile_text("aasimmallikk@gmail.com")` -> `UndefinedFunction`.
2. Forged an Auth.js session cookie with the real `AUTH_SECRET`
   (`@auth/core/jwt` `encode`, `salt: "authjs.session-token"`, `sub: "3"`) and
   hit `GET /api/auth/session` -> `{"user":{"name":…,"email":…,"id":"3"}}`.
3. `POST /api/chat` through the BFF with that cookie -> FastAPI
   `/ask/stream` -> streamed `OK` in ~6s.
4. `transactions` and `episodes` rows landed with `user_id = 3`.
5. `tsc --noEmit` clean. The remaining `npm run lint` error
   (`ThemeProvider.tsx`, setState-in-effect) and the ruff import-order
   warnings were already there before this change.

## Things noticed along the way (not fixed)

- Redis is not reachable on this machine (Docker is not enabled for this WSL
  distro). Only the non-streaming `POST /ask` answer cache uses it.
- PyJWT warns that `FASTAPI_JWT_SECRET` is 31 bytes; HS256 wants >= 32.
- The first `/ask/stream` request after a cold backend start took ~80s
  (MCP + OpenAI warm-up); subsequent requests were ~6s.

## Rule of thumb for next time

Anything that identifies the user has to agree across four places:

```
Auth.js token.sub  ->  session.user.id  ->  service JWT sub  ->  FastAPI user_id  ->  Postgres users.id (int)
```

If you change the type or source of one, walk the whole chain.
