export const runtime = "nodejs"

/**
 * Plans and prices for the signed-out homepage, in the visitor's currency.
 * Public, non-personal data (like /api/connectors), so no session: the only
 * input is the device timezone, which picks Indian (₹) or international ($)
 * prices exactly as checkout will (GET /billing/prices on the backend).
 * Unreachable backend = 503, and the page falls back to its own guess.
 */
export async function GET(req: Request) {
  const base = process.env.FASTAPI_URL
  const tz = new URL(req.url).searchParams.get("tz") ?? ""
  if (!base || !/^[A-Za-z0-9_+\-/]{0,64}$/.test(tz)) return Response.json({ detail: "unavailable" }, { status: 503 })
  try {
    const res = await fetch(`${base}/billing/prices?tz=${encodeURIComponent(tz)}`, { signal: AbortSignal.timeout(5_000), cache: "no-store" })
    if (!res.ok) return Response.json({ detail: "unavailable" }, { status: 503 })
    return Response.json(await res.json(), { headers: { "Cache-Control": "private, max-age=300" } })
  } catch {
    return Response.json({ detail: "unavailable" }, { status: 503 })
  }
}
