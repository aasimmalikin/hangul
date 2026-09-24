export const runtime = "nodejs"

/**
 * The connector catalogue for the "+ → Connectors" menu. Public, non-personal
 * data (which connectors exist), so like /api/quality it needs no session and
 * is fetched straight from the backend; unreachable backend = empty list, not
 * an error, so the menu degrades quietly.
 */
export async function GET() {
  const base = process.env.FASTAPI_URL
  if (!base) return Response.json([], { status: 200 })
  try {
    const res = await fetch(`${base}/connectors`, { signal: AbortSignal.timeout(5_000), cache: "no-store" })
    if (!res.ok) return Response.json([], { status: 200 })
    return Response.json(await res.json(), { headers: { "Cache-Control": "private, max-age=300" } })
  } catch {
    return Response.json([], { status: 200 })
  }
}
