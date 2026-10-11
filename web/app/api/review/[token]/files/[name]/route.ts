import { jsonError, rateLimit } from "@/lib/bff"
import { client, HEADERS, TOKEN } from "../../../_shared"

export const runtime = "nodejs"

/** One image of the post under review (the backend only serves that post's files). */
export async function GET(req: Request, { params }: { params: Promise<{ token: string; name: string }> }) {
  const { token, name } = await params
  const base = process.env.FASTAPI_URL
  if (!TOKEN.test(token) || !/^[A-Za-z0-9][A-Za-z0-9._ -]{0,200}$/.test(name)) return jsonError(404, "bad_request", "Not found.", HEADERS)
  const limited = rateLimit(`review-file:${client(req)}`, 240, 60_000)
  if (limited) return limited
  if (!base) return jsonError(502, "upstream_unreachable", "Hangul is unreachable right now.", HEADERS)
  try {
    const res = await fetch(`${base}/review/${token}/files/${encodeURIComponent(name)}`, { cache: "no-store", signal: AbortSignal.timeout(20_000) })
    if (!res.ok || !res.body) return jsonError(res.status === 410 ? 410 : 404, "bad_request", "Not found.", HEADERS)
    const headers: Record<string, string> = { ...HEADERS, "X-Content-Type-Options": "nosniff" }
    for (const h of ["content-type", "content-length"]) {
      const v = res.headers.get(h)
      if (v) headers[h] = v
    }
    return new Response(res.body, { status: 200, headers })
  } catch {
    return jsonError(502, "upstream_unreachable", "Hangul is unreachable right now.", HEADERS)
  }
}
