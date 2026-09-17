import { assertSameOrigin, jsonError, rateLimit, relayUpstreamError, requireUser, upstream, UpstreamError } from "@/lib/bff"

export const runtime = "nodejs"

/**
 * Forgets one remembered item. State-changing, so it gets the same-origin
 * check. Ownership is enforced by the backend (the row must belong to the
 * service token's `sub`); a foreign or unknown id comes back as 404.
 */
export async function DELETE(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const blocked = assertSameOrigin(req)
  if (blocked) return blocked
  const who = await requireUser()
  if (who instanceof Response) return who
  const limited = rateLimit(`memory:${who.userId}`, 60, 60_000)
  if (limited) return limited

  const { id } = await params
  if (!/^\d+$/.test(id)) return jsonError(400, "bad_request", "Invalid memory id.")

  let res: Response
  try {
    res = await upstream(`/memory/${id}`, who.userId, { method: "DELETE" }, { timeoutMs: 10_000, signal: req.signal })
  } catch (e) {
    if (e instanceof UpstreamError) return jsonError(e.status, e.code, e.message)
    throw e
  }
  if (!res.ok) return relayUpstreamError(res)

  return new Response(await res.text(), { status: 200, headers: { "Content-Type": "application/json" } })
}
