import { assertSameOrigin, jsonError, rateLimit, relayUpstreamError, requireUser, upstream, UpstreamError } from "@/lib/bff"

/**
 * One helper for every /api/vault/* route: same-origin check on mutations,
 * session, per-user rate limit, forward to FastAPI. Request bodies (which may
 * hold a secret) are passed through untouched and never logged.
 */
export async function vaultProxy(
  req: Request,
  path: string,
  init: { method: "GET" | "POST" | "DELETE"; body?: string },
) {
  if (init.method !== "GET") {
    const blocked = assertSameOrigin(req)
    if (blocked) return blocked
  }
  const who = await requireUser()
  if (who instanceof Response) return who
  const limited = rateLimit(`vault:${who.userId}`, 60, 60_000)
  if (limited) return limited

  let res: Response
  try {
    res = await upstream(
      path,
      who.userId,
      {
        method: init.method,
        body: init.body,
        headers: init.body ? { "Content-Type": "application/json" } : undefined,
        cache: "no-store",
      },
      { timeoutMs: 15_000, signal: req.signal },
    )
  } catch (e) {
    if (e instanceof UpstreamError) return jsonError(e.status, e.code, e.message)
    throw e
  }
  if (!res.ok) return relayUpstreamError(res)
  return new Response(await res.text(), {
    status: res.status,
    headers: { "Content-Type": "application/json", "Cache-Control": "private, no-store" },
  })
}

export function idOr400(id: string, what: string): Response | null {
  return /^\d+$/.test(id) ? null : jsonError(400, "bad_request", `Invalid ${what} id.`)
}
