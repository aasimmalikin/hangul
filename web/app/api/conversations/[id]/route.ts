import { assertSameOrigin, jsonError, rateLimit, relayUpstreamError, requireUser, upstream, UpstreamError } from "@/lib/bff"

export const runtime = "nodejs"

// Conversation ids are uuid4().hex, so 32 hex chars. Checked here so a
// path-shaped id never reaches the backend.
const ID = /^[0-9a-f]{1,64}$/
const MAX_TITLE = 200

/** One conversation with its transcript, for rehydrating the chat page. */
export async function GET(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const who = await requireUser()
  if (who instanceof Response) return who
  const limited = rateLimit(`convs-read:${who.userId}`, 240, 60_000)
  if (limited) return limited

  const { id } = await params
  if (!ID.test(id)) return jsonError(400, "bad_request", "Invalid conversation id.")

  let res: Response
  try {
    res = await upstream(`/conversations/${id}`, who.userId, { method: "GET", cache: "no-store" }, { timeoutMs: 15_000, signal: req.signal })
  } catch (e) {
    if (e instanceof UpstreamError) return jsonError(e.status, e.code, e.message)
    throw e
  }
  if (!res.ok) return relayUpstreamError(res)
  return new Response(await res.text(), { status: 200, headers: { "Content-Type": "application/json", "Cache-Control": "private, no-store" } })
}

/** Rename. Ownership is the backend's WHERE clause; a foreign id is a 404. */
export async function PATCH(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const blocked = assertSameOrigin(req)
  if (blocked) return blocked
  const who = await requireUser()
  if (who instanceof Response) return who
  const limited = rateLimit(`convs-write:${who.userId}`, 60, 60_000)
  if (limited) return limited

  const { id } = await params
  if (!ID.test(id)) return jsonError(400, "bad_request", "Invalid conversation id.")

  let body: Record<string, unknown>
  try { body = await req.json() } catch { return jsonError(400, "bad_request", "Malformed request.") }
  const title = body.title
  if (typeof title !== "string" || !title.trim() || title.length > MAX_TITLE) {
    return jsonError(400, "bad_request", "Invalid title.")
  }

  let res: Response
  try {
    res = await upstream(`/conversations/${id}`, who.userId, {
      method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title }),
    }, { timeoutMs: 10_000, signal: req.signal })
  } catch (e) {
    if (e instanceof UpstreamError) return jsonError(e.status, e.code, e.message)
    throw e
  }
  if (!res.ok) return relayUpstreamError(res)
  return new Response(await res.text(), { status: 200, headers: { "Content-Type": "application/json" } })
}

/** Hides one conversation; the transcript stays for audit. */
export async function DELETE(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const blocked = assertSameOrigin(req)
  if (blocked) return blocked
  const who = await requireUser()
  if (who instanceof Response) return who
  const limited = rateLimit(`convs-write:${who.userId}`, 60, 60_000)
  if (limited) return limited

  const { id } = await params
  if (!ID.test(id)) return jsonError(400, "bad_request", "Invalid conversation id.")

  let res: Response
  try {
    res = await upstream(`/conversations/${id}`, who.userId, { method: "DELETE" }, { timeoutMs: 10_000, signal: req.signal })
  } catch (e) {
    if (e instanceof UpstreamError) return jsonError(e.status, e.code, e.message)
    throw e
  }
  if (!res.ok) return relayUpstreamError(res)
  return new Response(await res.text(), { status: 200, headers: { "Content-Type": "application/json" } })
}
