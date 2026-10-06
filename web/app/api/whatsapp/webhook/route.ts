import { jsonError } from "@/lib/bff"

export const runtime = "nodejs"

/**
 * Meta (WhatsApp Cloud API) -> FastAPI webhook relay. Like the Dodo webhook,
 * deliberately NOT on the BFF rails: Meta has no session. It's authenticated
 * by `X-Hub-Signature-256` over the exact bytes (checked by the backend), so
 * the raw body and that header are forwarded untouched. GET is Meta's one-time
 * check (hub.mode / hub.verify_token / hub.challenge).
 * Callback URL to give Meta: https://<this site>/api/whatsapp/webhook
 */
export async function GET(req: Request) {
  const base = process.env.FASTAPI_URL
  if (!base) return jsonError(502, "upstream_unreachable", "Backend is not configured.")
  const query = new URL(req.url).search
  try {
    const res = await fetch(`${base}/whatsapp/webhook${query}`, { signal: AbortSignal.timeout(10_000) })
    return new Response(await res.text(), { status: res.status, headers: { "Content-Type": "text/plain" } })
  } catch {
    return jsonError(502, "upstream_unreachable", "Backend unreachable.")
  }
}

export async function POST(req: Request) {
  const base = process.env.FASTAPI_URL
  if (!base) return jsonError(502, "upstream_unreachable", "Backend is not configured.")
  const raw = await req.arrayBuffer()
  try {
    const res = await fetch(`${base}/whatsapp/webhook`, {
      method: "POST",
      body: raw,
      headers: { "Content-Type": "application/json", "X-Hub-Signature-256": req.headers.get("x-hub-signature-256") ?? "" },
      signal: AbortSignal.timeout(15_000),
    })
    return new Response(await res.text(), { status: res.status, headers: { "Content-Type": "application/json" } })
  } catch {
    // a non-2xx makes Meta retry the delivery later
    return jsonError(502, "upstream_unreachable", "Backend unreachable.")
  }
}
