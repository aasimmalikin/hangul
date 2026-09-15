# Google sign-in failing with `CallbackRouteError: fetch failed (ETIMEDOUT)`

## Symptom

Clicking "Sign in with Google" bounced through Google fine, then landed on
`/api/auth/error?error=Configuration` with this in the Next.js dev log:

```
[auth][error] CallbackRouteError: Read more at https://errors.authjs.dev#callbackrouteerror
[auth][cause]: TypeError: fetch failed
[auth][details]: { "code": "ETIMEDOUT", "provider": "google" }
```

It happened often but not every time.

## Why it kept happening

The OAuth flow has two halves:

1. **Browser → Google → browser.** Google authenticates you and redirects back
   to `/api/auth/callback/google?code=...`. This half always worked (the log
   shows the callback arriving with a `code`).
2. **Next.js server → Google.** Auth.js then exchanges that `code` for tokens by
   calling `https://oauth2.googleapis.com/token` from Node, and fetches
   userinfo. This half was timing out.

`error=Configuration` is a red herring: Auth.js reports *any* exception inside
the callback route under that name, so it looked like a bad client ID/secret
when the config was actually fine.

Root cause, established by probing from inside WSL2:

- `oauth2.googleapis.com` resolves to a **single** IP, `192.178.158.95`, from
  every resolver tried (8.8.8.8, 1.1.1.1, 9.9.9.9, the Windows host resolver).
- Fresh TCP connections to that IP fail ~40-50% of the time from this network
  path (`curl --resolve` against that IP: 3-5 failures out of 8). The other
  Google front-ends (`www.googleapis.com` → `172.217.11x.4`) were 8/8 every
  time, and `api.github.com`, `registry.npmjs.org` etc. were all 10/10. So it
  is not general WSL2 connectivity; it is a bad path to that one Google prefix.
- Node 24's Happy-Eyeballs (`autoSelectFamily`) makes it worse: the attempt
  window is 250 ms, and the fallback IPv6 address is unreachable because WSL2
  has no global IPv6 route, so a slow IPv4 SYN turns into a fast `ETIMEDOUT`
  (~400 ms) instead of a slow-but-successful connect.
- Auth.js does that token exchange with a single, un-retried `fetch`, so one
  dropped SYN = whole sign-in fails.

## What was changed

**App-side resilience (committed to the repo):**

- [web/lib/resilientFetch.ts](../../web/lib/resilientFetch.ts) — a `fetch`
  wrapper that retries connection-level failures (`ETIMEDOUT`, `ECONNRESET`,
  `EAI_AGAIN`, ...) up to 4 attempts with a short backoff and an 8 s per-attempt
  timeout. It logs each retry as `[auth] fetch ... failed (ETIMEDOUT); retry n/3`.
- [web/auth.config.ts](../../web/auth.config.ts) — the Google provider now
  passes that wrapper via Auth.js's `[customFetch]` symbol, so the token and
  userinfo calls go through it.

Verified against the live endpoint: 10/10 successes, with 3 of those runs
needing one or two retries that previously would have been hard failures.

**Local network fix (needs sudo, not committed):**

Pin the OAuth host to a healthy Google front-end. Google serves every
`*.googleapis.com` host from any front-end (routing is by SNI, and the TLS
cert validates), so this is safe:

```bash
echo "172.217.116.4 oauth2.googleapis.com" | sudo tee -a /etc/hosts
```

Remove the line when your route to `192.178.158.95` recovers, or if Google
ever changes that front-end IP. Alternative without touching `/etc/hosts`:
run dev with a longer Happy-Eyeballs window so slow SYNs are not abandoned:

```bash
NODE_OPTIONS="--network-family-autoselection-attempt-timeout=2000" npm run dev
```

That alone reduced failures but did not eliminate them, because some SYNs to
that IP never get an answer at all.

## How to tell if it comes back

```bash
for i in $(seq 1 10); do curl -4 -s -o /dev/null -m 4 -w "%{http_code}\n" https://oauth2.googleapis.com/token; done
```

Any `000` lines mean dropped connections. If it is all `000` (not intermittent),
that is a different problem — check a VPN/firewall on the Windows side.
