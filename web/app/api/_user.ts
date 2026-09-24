import { assertSameOrigin, jsonError, rateLimit, relayUpstreamError, requireUser, upstream, UpstreamError } from "@/lib/bff"

/** Plain per-user pass-through for the settings / tasks routes (same rails as memory). */
export async function userProxy(req: Request, path: string, init: { method: "GET" | "POST" | "PUT" | "DELETE"; body?: string }) {
  if (init.method !== "GET") {
    const blocked = assertSameOrigin(req)
    if (blocked) return blocked
  }
  const who = await requireUser()
  if (who instanceof Response) return who
  const limited = rateLimit(`settings:${who.userId}`, 60, 60_000)
  if (limited) return limited
  let res: Response
  try {
    res = await upstream(path, who.userId, { method: init.method, body: init.body, headers: init.body ? { "Content-Type": "application/json" } : undefined, cache: "no-store" },
      { timeoutMs: init.method === "POST" && path.endsWith("/run") ? 120_000 : 15_000, signal: req.signal })
  } catch (e) {
    if (e instanceof UpstreamError) return jsonError(e.status, e.code, e.message)
    throw e
  }
  if (!res.ok) return relayUpstreamError(res)
  return new Response(await res.text(), { status: res.status, headers: { "Content-Type": "application/json", "Cache-Control": "private, no-store" } })
}

export const idOr400 = (id: string) => (/^\d+$/.test(id) ? null : jsonError(400, "bad_request", "Invalid id."))
