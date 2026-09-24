import { assertSameOrigin, jsonError, rateLimit, relayUpstreamError, requireUser, upstream, UpstreamError } from "@/lib/bff"

export const runtime = "nodejs"

/**
 * The signed-in user's conversations, most recently touched first.
 *
 * This is what the "Chats" rail reads. It replaces the old /api/chats list
 * (which read `/episodes`, a client-written summary): the backend owns the
 * transcript now, so these rows are the real conversations and each one can be
 * reopened.
 */
export async function GET() {
  const who = await requireUser()
  if (who instanceof Response) return who
  // Read on every page load; its own generous bucket so browsing never
  // competes with creates/renames for the limit.
  const limited = rateLimit(`convs-list:${who.userId}`, 240, 60_000)
  if (limited) return limited

  let res: Response
  try {
    res = await upstream("/conversations", who.userId, { method: "GET", cache: "no-store" }, { timeoutMs: 10_000 })
  } catch (e) {
    if (e instanceof UpstreamError) return jsonError(e.status, e.code, e.message)
    throw e
  }
  if (!res.ok) return relayUpstreamError(res)
  return new Response(await res.text(), { status: 200, headers: { "Content-Type": "application/json", "Cache-Control": "private, no-store" } })
}

// Mirrors ConversationIn on the backend; refused here so junk never crosses the wire.
const MAX_TITLE = 200
const MODES = new Set(["default", "research"])

/**
 * Start an empty conversation ("New chat"). Not required to chat: /api/chat
 * creates one implicitly on the first message and returns its id.
 */
export async function POST(req: Request) {
  const blocked = assertSameOrigin(req)
  if (blocked) return blocked
  const who = await requireUser()
  if (who instanceof Response) return who
  const limited = rateLimit(`convs-write:${who.userId}`, 60, 60_000)
  if (limited) return limited

  let body: Record<string, unknown> = {}
  try { body = (await req.json()) as Record<string, unknown> } catch { /* an empty body is fine */ }

  const title = typeof body.title === "string" ? body.title.slice(0, MAX_TITLE) : ""
  const mode = typeof body.mode === "string" && MODES.has(body.mode) ? body.mode : "default"
  const connectors = Array.isArray(body.connectors)
    ? body.connectors.filter((c): c is string => typeof c === "string").slice(0, 8)
    : []
  const out = {
    title, mode, connectors,
    docs_only: body.docsOnly === true,
    model: typeof body.model === "string" ? body.model : null,
    effort: typeof body.effort === "string" ? body.effort : null,
  }

  let res: Response
  try {
    res = await upstream("/conversations", who.userId, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(out),
    }, { timeoutMs: 10_000, signal: req.signal })
  } catch (e) {
    if (e instanceof UpstreamError) return jsonError(e.status, e.code, e.message)
    throw e
  }
  if (!res.ok) return relayUpstreamError(res)
  return new Response(await res.text(), { status: 201, headers: { "Content-Type": "application/json" } })
}
