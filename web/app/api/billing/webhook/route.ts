import { jsonError } from "@/lib/bff"

export const runtime = "nodejs"

/**
 * Dodo Payments -> FastAPI webhook relay. Deliberately NOT on the BFF rails:
 * Dodo has no session and is cross-site by definition. It is authenticated by
 * its Standard Webhooks signature (`webhook-id` / `-timestamp` / `-signature`
 * over the exact bytes), which only the backend checks -- so the raw body and
 * those three headers must be forwarded untouched.
 */
export async function POST(req: Request) {
  const base = process.env.FASTAPI_URL
  if (!base) return jsonError(502, "upstream_unreachable", "Backend is not configured.")
  const raw = await req.arrayBuffer()
  try {
    const res = await fetch(`${base}/billing/webhook`, {
      method: "POST",
      body: raw,
      headers: {
        "Content-Type": "application/json",
        "webhook-id": req.headers.get("webhook-id") ?? "",
        "webhook-timestamp": req.headers.get("webhook-timestamp") ?? "",
        "webhook-signature": req.headers.get("webhook-signature") ?? "",
      },
      signal: AbortSignal.timeout(15_000),
    })
    return new Response(await res.text(), { status: res.status, headers: { "Content-Type": "application/json" } })
  } catch {
    // a non-2xx makes Dodo retry the delivery later
    return jsonError(502, "upstream_unreachable", "Backend unreachable.")
  }
}
