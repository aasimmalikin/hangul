import { assertSameOrigin, jsonError, rateLimit, relayUpstreamError, requireUser, upstream, UpstreamError } from "@/lib/bff"

export const runtime = "nodejs"

/** Disconnect Google Workspace: the backend forgets the refresh token and closes the user's MCP sessions. */
export async function DELETE(req: Request) {
  const blocked = assertSameOrigin(req)
  if (blocked) return blocked
  const who = await requireUser()
  if (who instanceof Response) return who
  const limited = rateLimit(`integrations:${who.userId}`, 60, 60_000)
  if (limited) return limited
  let res: Response
  try {
    res = await upstream("/integrations/google", who.userId, { method: "DELETE" }, { timeoutMs: 10_000, signal: req.signal })
  } catch (e) {
    if (e instanceof UpstreamError) return jsonError(e.status, e.code, e.message)
    throw e
  }
  if (!res.ok) return relayUpstreamError(res)
  return new Response(await res.text(), { status: 200, headers: { "Content-Type": "application/json" } })
}
