import { assertSameOrigin, jsonError, rateLimit } from "@/lib/bff"
import { client, HEADERS, TOKEN } from "../_shared"

export const runtime = "nodejs"

/**
 * Client review (harness.brands.review): the client opens the post (GET) and
 * approves it or asks for changes (POST). Off the session rails like the
 * approve-by-link relay: the signed link is the credential and the backend checks
 * it. Rate-limited per address, same-origin on POST, never cached or indexed.
 */
async function relay(req: Request, token: string, init: RequestInit): Promise<Response> {
  const base = process.env.FASTAPI_URL
  if (!TOKEN.test(token)) return jsonError(410, "bad_request", "This review link has expired or isn't valid.", HEADERS)
  const limited = rateLimit(`review-link:${client(req)}`, 60, 60_000)
  if (limited) return limited
  if (!base) return jsonError(502, "upstream_unreachable", "Hangul is unreachable right now.", HEADERS)
  try {
    const res = await fetch(`${base}/review/${token}`, { ...init, cache: "no-store", signal: AbortSignal.timeout(15_000) })
    return new Response(await res.text(), { status: res.status, headers: { "Content-Type": "application/json", ...HEADERS } })
  } catch {
    return jsonError(502, "upstream_unreachable", "Hangul is unreachable right now. Try again in a minute.", HEADERS)
  }
}

export async function GET(req: Request, { params }: { params: Promise<{ token: string }> }) {
  const { token } = await params
  return relay(req, token, { method: "GET" })
}

export async function POST(req: Request, { params }: { params: Promise<{ token: string }> }) {
  const blocked = assertSameOrigin(req)
  if (blocked) return blocked
  const { token } = await params
  let b: { decision?: unknown; comment?: unknown; name?: unknown } = {}
  try { b = await req.json() } catch { /* bad body */ }
  if (b.decision !== "approve" && b.decision !== "changes") return jsonError(400, "bad_request", "Choose approve or changes.", HEADERS)
  const body = JSON.stringify({ decision: b.decision, comment: String(b.comment ?? "").slice(0, 2000), name: String(b.name ?? "").slice(0, 80) })
  return relay(req, token, { method: "POST", body, headers: { "Content-Type": "application/json" } })
}
