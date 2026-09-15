import { assertSameOrigin, jsonError, rateLimit, relayUpstreamError, requireUser, upstream, UpstreamError } from "@/lib/bff"

export const runtime = "nodejs"
export const maxDuration = 300

/**
 * Relays a human approval decision to the backend, which resumes the paused
 * run from its checkpoint. The backend verifies the caller owns the run and
 * claims the pending action atomically, so a double-click or a retry after a
 * timeout cannot execute the tool twice.
 */
export async function POST(req: Request) {
  const blocked = assertSameOrigin(req)
  if (blocked) return blocked
  const who = await requireUser()
  if (who instanceof Response) return who
  const limited = rateLimit(`approve:${who.userId}`, 30, 60_000)
  if (limited) return limited

  let body: { approval_id?: unknown; decision?: unknown; choice?: unknown }
  try {
    body = await req.json()
  } catch {
    return jsonError(400, "bad_request", "Malformed request body.")
  }
  const { approval_id, decision, choice } = body
  if (typeof approval_id !== "string" || !/^[\w-]{1,64}$/.test(approval_id)) {
    return jsonError(400, "bad_request", "Invalid approval id.")
  }
  if (decision !== "approve" && decision !== "reject") {
    return jsonError(400, "bad_request", "Decision must be approve or reject.")
  }
  if (choice !== undefined && choice !== null && (typeof choice !== "string" || choice.length > 500)) {
    return jsonError(400, "bad_request", "Invalid choice.")
  }

  let res: Response
  try {
    res = await upstream("/approve", who.userId, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ approval_id, decision, choice: choice ?? null }),
    }, { timeoutMs: 290_000, signal: req.signal })
  } catch (e) {
    if (e instanceof UpstreamError) return jsonError(e.status, e.code, e.message)
    throw e
  }
  if (!res.ok) return relayUpstreamError(res)

  return new Response(await res.text(), { status: 200, headers: { "Content-Type": "application/json" } })
}
