import { jsonError, rateLimit, relayUpstreamError, requireUser, upstream, UpstreamError } from "@/lib/bff"

export const runtime = "nodejs"

/**
 * Download one of the user's own files (a created document, a chart, an
 * upload) -- streamed through from backend `GET /files/<name>` with its type
 * and Content-Disposition, so <img src> shows charts and links download docs.
 */
export async function GET(req: Request, { params }: { params: Promise<{ name: string }> }) {
  const { name } = await params
  if (!/^[A-Za-z0-9][A-Za-z0-9._ -]{0,200}$/.test(name)) return jsonError(404, "bad_request", "No such file.")
  const who = await requireUser()
  if (who instanceof Response) return who
  const limited = rateLimit(`files:${who.userId}`, 120, 60_000)
  if (limited) return limited
  let res: Response
  try {
    res = await upstream(`/files/${encodeURIComponent(name)}`, who.userId, { method: "GET", cache: "no-store" }, { timeoutMs: 30_000, signal: req.signal })
  } catch (e) {
    if (e instanceof UpstreamError) return jsonError(e.status, e.code, e.message)
    throw e
  }
  if (!res.ok || !res.body) return relayUpstreamError(res)
  const headers: Record<string, string> = { "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff" }
  for (const h of ["content-type", "content-disposition", "content-length"]) {
    const v = res.headers.get(h)
    if (v) headers[h] = v
  }
  return new Response(res.body, { status: 200, headers })
}
