import { assertSameOrigin, jsonError, rateLimit } from "@/lib/bff"

export const runtime = "nodejs"

/**
 * Pre-registration (/join). Public like /api/billing/prices: no session, because
 * the people joining don't have accounts yet. POST is same-origin and limited per
 * address; the backend answers the same whether the email is new or already on
 * the list, so this can't be used to check who signed up.
 */
const HEADERS = { "Cache-Control": "private, no-store" }
const PERSONAS = new Set(["", "founder", "student", "professional", "personal"])
const INTERESTS = new Set(["", "free", "plus", "pro"])
const TRADES = new Set(["", "retail_shop", "cafe", "cloud_kitchen", "salon", "d2c_brand", "other"])

function client(req: Request): string {
  return (req.headers.get("x-forwarded-for") ?? "").split(",")[0].trim() || "direct"
}

async function upstream(path: string, init: RequestInit): Promise<Response> {
  const base = process.env.FASTAPI_URL
  if (!base) return jsonError(502, "upstream_unreachable", "Hangul is unreachable right now.", HEADERS)
  try {
    const res = await fetch(`${base}${path}`, { ...init, cache: "no-store", signal: AbortSignal.timeout(8_000) })
    return new Response(await res.text(), { status: res.status, headers: { "Content-Type": "application/json", ...HEADERS } })
  } catch {
    return jsonError(502, "upstream_unreachable", "Hangul is unreachable right now. Try again in a minute.", HEADERS)
  }
}

export async function GET(req: Request) {
  const limited = rateLimit(`waitlist-count:${client(req)}`, 60, 60_000)
  if (limited) return limited
  return upstream("/waitlist/count", { method: "GET" })
}

export async function POST(req: Request) {
  const blocked = assertSameOrigin(req)
  if (blocked) return blocked
  const limited = rateLimit(`waitlist-join:${client(req)}`, 5, 10 * 60_000)
  if (limited) return limited
  let b: { email?: unknown; persona?: unknown; interest?: unknown; source?: unknown; trade?: unknown; city?: unknown } = {}
  try { b = await req.json() } catch { /* bad body */ }
  const email = String(b.email ?? "").trim().slice(0, 254)
  const persona = String(b.persona ?? "")
  const interest = String(b.interest ?? "")
  const trade = String(b.trade ?? "")
  if (!email.includes("@")) return jsonError(422, "bad_request", "That doesn't look like an email address.", HEADERS)
  if (!PERSONAS.has(persona) || !INTERESTS.has(interest) || !TRADES.has(trade)) return jsonError(422, "bad_request", "Check the form and try again.", HEADERS)
  const body = JSON.stringify({ email, persona, interest, trade, city: String(b.city ?? "").slice(0, 80),
    source: String(b.source ?? "").slice(0, 80) })
  return upstream("/waitlist", { method: "POST", body, headers: { "Content-Type": "application/json" } })
}
