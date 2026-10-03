import { assertSameOrigin, jsonError, rateLimit, relayUpstreamError, requireUser, upstream, UpstreamError } from "@/lib/bff"

export const runtime = "nodejs"

const APPS = new Set(["github", "notion", "slack"])

/** Connect (POST {token}) or disconnect (DELETE) GitHub / Notion / Slack; the token goes straight to the backend vault. */
async function relay(req: Request, app: string, method: "POST" | "DELETE") {
  if (!APPS.has(app)) return jsonError(404, "bad_request", "Unknown app.")
  const blocked = assertSameOrigin(req)
  if (blocked) return blocked
  const who = await requireUser()
  if (who instanceof Response) return who
  const limited = rateLimit(`integrations:${who.userId}`, 20, 60_000)
  if (limited) return limited
  let res: Response
  try {
    res = await upstream(`/integrations/apps/${app}`, who.userId, {
      method, headers: { "Content-Type": "application/json" },
      body: method === "POST" ? await req.text() : undefined,
    }, { timeoutMs: 20_000, signal: req.signal })
  } catch (e) {
    if (e instanceof UpstreamError) return jsonError(e.status, e.code, e.message)
    throw e
  }
  if (!res.ok) return relayUpstreamError(res)
  return new Response(await res.text(), { status: 200, headers: { "Content-Type": "application/json", "Cache-Control": "no-store" } })
}

export async function POST(req: Request, { params }: { params: Promise<{ app: string }> }) {
  return relay(req, (await params).app, "POST")
}
export async function DELETE(req: Request, { params }: { params: Promise<{ app: string }> }) {
  return relay(req, (await params).app, "DELETE")
}
