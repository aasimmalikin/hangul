import { assertSameOrigin, jsonError, rateLimit } from "@/lib/bff"

export const runtime = "nodejs"

/**
 * Approve-by-link (the "needs your approval" email and notification): show the
 * waiting action (GET) and decide it (POST). Deliberately off the session rails,
 * like the webhooks: the signed link is the credential, and the backend checks it
 * (harness.approval_links). Rate-limited per client address, same-origin on POST
 * so another site can't submit a decision, never cached, never indexed.
 */
const TOKEN = /^[A-Za-z0-9_-]{8,200}\.[A-Za-z0-9_-]{20,100}$/
const HEADERS = { "Cache-Control": "private, no-store", "X-Robots-Tag": "noindex, nofollow", "Referrer-Policy": "no-referrer" }

function client(req: Request): string {
  return (req.headers.get("x-forwarded-for") ?? "").split(",")[0].trim() || "direct"
}

async function relay(req: Request, token: string, init: RequestInit): Promise<Response> {
  const base = process.env.FASTAPI_URL
  if (!TOKEN.test(token)) return jsonError(410, "bad_request", "This link has expired or isn't valid.", HEADERS)
  const limited = rateLimit(`approval-link:${client(req)}`, 30, 60_000)
  if (limited) return limited
  if (!base) return jsonError(502, "upstream_unreachable", "Hangul is unreachable right now.", HEADERS)
  try {
    const res = await fetch(`${base}/approval-links/${token}`, {
      ...init, cache: "no-store",
      // approving resumes the run (a model turn), so allow it time
      signal: AbortSignal.timeout(init.method === "POST" ? 120_000 : 10_000),
    })
    const body = await res.text()
    return new Response(body, { status: res.status, headers: { "Content-Type": "application/json", ...HEADERS } })
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
  let decision = ""
  try { decision = String((await req.json()).decision ?? "") } catch { /* bad body */ }
  if (decision !== "approve" && decision !== "reject") return jsonError(400, "bad_request", "Choose approve or reject.", HEADERS)
  return relay(req, token, { method: "POST", body: JSON.stringify({ decision }), headers: { "Content-Type": "application/json" } })
}
