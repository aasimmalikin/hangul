import { requireUser } from "@/lib/bff"

export const runtime = "nodejs"

/**
 * The latest eval report and CI-gate verdict, for the "answer quality" card
 * in the account menu. Aggregate numbers only — no user data — but still
 * behind the session so it is not a public endpoint.
 */
export async function GET() {
  const who = await requireUser()
  if (who instanceof Response) return who
  const base = process.env.FASTAPI_URL
  if (!base) return Response.json({ available: false }, { status: 200 })
  try {
    const res = await fetch(`${base}/quality`, { signal: AbortSignal.timeout(5_000), cache: "no-store" })
    if (!res.ok) return Response.json({ available: false }, { status: 200 })
    return Response.json(await res.json(), { headers: { "Cache-Control": "private, max-age=60" } })
  } catch {
    return Response.json({ available: false }, { status: 200 })
  }
}
