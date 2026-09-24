import { jsonError, rateLimit, relayUpstreamError, requireUser, upstream, UpstreamError } from "@/lib/bff"

export const runtime = "nodejs"

/** What the signed-in user has connected (Google Workspace products with granted scopes). */
export async function GET() {
  const who = await requireUser()
  if (who instanceof Response) return who
  const limited = rateLimit(`integrations:${who.userId}`, 60, 60_000)
  if (limited) return limited
  let res: Response
  try {
    res = await upstream("/integrations", who.userId, { method: "GET", cache: "no-store" }, { timeoutMs: 10_000 })
  } catch (e) {
    if (e instanceof UpstreamError) return jsonError(e.status, e.code, e.message)
    throw e
  }
  if (!res.ok) return relayUpstreamError(res)
  return new Response(await res.text(), { status: 200, headers: { "Content-Type": "application/json", "Cache-Control": "private, no-store" } })
}
