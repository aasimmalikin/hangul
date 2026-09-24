import { assertSameOrigin, jsonError, rateLimit, relayUpstreamError, requireAdmin, upstream, UpstreamError } from "@/lib/bff"

/** Headers every admin response carries: never cached, never indexed. */
const ADMIN_HEADERS = {
  "Content-Type": "application/json",
  "Cache-Control": "private, no-store, max-age=0",
  "X-Robots-Tag": "noindex, nofollow",
}

/**
 * Every /api/admin/* route, in order:
 *   1. same-origin on anything that changes state (browsers only; CSRF)
 *   2. a session that could be an admin: Google-backed and recent (requireAdmin)
 *   3. a per-user rate limit
 *   4. FastAPI, with a 5-minute service token that carries the Google email;
 *      the backend applies its own allowlist and IP rules and audits the call
 * A 403 from the backend ("email not authorised") is relayed as-is so the page
 * can tell the person this account is simply not on the list.
 */
export async function adminProxy(req: Request, path: string, init: { method: "GET" | "POST"; body?: string }) {
  if (init.method !== "GET") {
    const blocked = assertSameOrigin(req)
    if (blocked) return blocked
  }
  const who = await requireAdmin()
  if (who instanceof Response) return who
  const limited = rateLimit(`admin:${who.userId}`, 120, 60_000)
  if (limited) return limited

  let res: Response
  try {
    res = await upstream(
      path,
      who.userId,
      { method: init.method, body: init.body, headers: init.body ? { "Content-Type": "application/json" } : undefined, cache: "no-store" },
      { timeoutMs: 15_000, signal: req.signal, identity: who.identity },
    )
  } catch (e) {
    if (e instanceof UpstreamError) return jsonError(e.status, e.code, e.message, ADMIN_HEADERS)
    throw e
  }
  if (res.status === 403 || res.status === 401) {
    // the backend's own verdict on this identity: not on the allowlist / wrong
    // network (403), or the sign-in is too old for it (401) -- both are about
    // the person, not about our service token, so relay them as such
    let detail = res.status === 403 ? "This account is not an administrator." : "Sign in again with Google."
    try { const b = await res.json(); if (typeof b?.detail === "string") detail = b.detail } catch { /* not JSON */ }
    return jsonError(res.status, res.status === 403 ? "forbidden" : "reauth_required", detail, ADMIN_HEADERS)
  }
  if (!res.ok) return relayUpstreamError(res)
  return new Response(await res.text(), { status: res.status, headers: ADMIN_HEADERS })
}
