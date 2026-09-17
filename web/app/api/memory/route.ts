import { jsonError, rateLimit, relayUpstreamError, requireUser, upstream, UpstreamError } from "@/lib/bff"

export const runtime = "nodejs"

/**
 * Lists what the agent has remembered about the signed-in user (the
 * `remember` tool's output). Read-only, so no same-origin check — but it is
 * personal data, so it stays behind the session and is never cached.
 */
export async function GET() {
  const who = await requireUser()
  if (who instanceof Response) return who
  const limited = rateLimit(`memory:${who.userId}`, 60, 60_000)
  if (limited) return limited

  let res: Response
  try {
    res = await upstream("/memory", who.userId, { method: "GET", cache: "no-store" }, { timeoutMs: 10_000 })
  } catch (e) {
    if (e instanceof UpstreamError) return jsonError(e.status, e.code, e.message)
    throw e
  }
  if (!res.ok) return relayUpstreamError(res)

  return new Response(await res.text(), {
    status: 200,
    headers: { "Content-Type": "application/json", "Cache-Control": "private, no-store" },
  })
}
