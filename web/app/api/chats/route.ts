import { assertSameOrigin, jsonError, rateLimit, relayUpstreamError, requireUser, upstream, UpstreamError } from "@/lib/bff"

export const runtime = "nodejs"

/** The signed-in user's conversations (the "Chats" rail), most recent first. */
export async function GET() {
  const who = await requireUser()
  if (who instanceof Response) return who
  // Fetched on every page load and after every run; its own generous
  // bucket so browsing never competes with saves/deletes for the limit.
  const limited = rateLimit(`chats-list:${who.userId}`, 240, 60_000)
  if (limited) return limited

  let res: Response
  try {
    res = await upstream("/episodes", who.userId, { method: "GET", cache: "no-store" }, { timeoutMs: 10_000 })
  } catch (e) {
    if (e instanceof UpstreamError) return jsonError(e.status, e.code, e.message)
    throw e
  }
  if (!res.ok) return relayUpstreamError(res)
  return new Response(await res.text(), { status: 200, headers: { "Content-Type": "application/json", "Cache-Control": "private, no-store" } })
}

// Mirrors EpisodeIn on the backend; refused here so junk never crosses the wire.
const MAX = { thread_id: 64, title: 200, summary: 2048 } as const

/**
 * Save (or refresh) one conversation. The client sends its own compact
 * summary of the transcript; the backend embeds it so the agent's
 * `recall_episodes` tool can find it later.
 */
export async function POST(req: Request) {
  const blocked = assertSameOrigin(req)
  if (blocked) return blocked
  const who = await requireUser()
  if (who instanceof Response) return who
  const limited = rateLimit(`chats-save:${who.userId}`, 60, 60_000)
  if (limited) return limited

  let body: Record<string, unknown>
  try { body = await req.json() } catch { return jsonError(400, "bad_request", "Malformed request.") }
  const out: Record<string, string> = {}
  for (const k of ["thread_id", "title", "summary"] as const) {
    const v = body[k]
    if (typeof v !== "string" || !v.trim() || v.length > MAX[k]) return jsonError(400, "bad_request", `Invalid ${k}.`)
    out[k] = v
  }

  let res: Response
  try {
    res = await upstream("/episodes", who.userId, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(out),
    }, { timeoutMs: 20_000, signal: req.signal })
  } catch (e) {
    if (e instanceof UpstreamError) return jsonError(e.status, e.code, e.message)
    throw e
  }
  if (!res.ok) return relayUpstreamError(res)
  return new Response(await res.text(), { status: 200, headers: { "Content-Type": "application/json" } })
}
