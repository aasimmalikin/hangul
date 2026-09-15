export const runtime = "nodejs"

/**
 * Is the assistant backend reachable? Polled by the UI's status banner.
 * Deliberately unauthenticated and cheap: it reveals nothing but up/down.
 */
export async function GET() {
  const base = process.env.FASTAPI_URL
  if (!base) return Response.json({ ok: false }, { status: 503, headers: { "Cache-Control": "no-store" } })
  try {
    const res = await fetch(`${base}/healthz`, { signal: AbortSignal.timeout(3_000), cache: "no-store" })
    return Response.json({ ok: res.ok }, { status: res.ok ? 200 : 503, headers: { "Cache-Control": "no-store" } })
  } catch {
    return Response.json({ ok: false }, { status: 503, headers: { "Cache-Control": "no-store" } })
  }
}
