import { assertSameOrigin, jsonError, rateLimit, relayUpstreamError, requireUser, upstream, UpstreamError } from "@/lib/bff"

export const runtime = "nodejs"
export const maxDuration = 60

/** Text -> spoken MP3, streamed through as it is generated (backend `POST /voice/speak`, metered). */
export async function POST(req: Request) {
  const blocked = assertSameOrigin(req)
  if (blocked) return blocked
  const who = await requireUser()
  if (who instanceof Response) return who
  const limited = rateLimit(`speak:${who.userId}`, 60, 60_000)
  if (limited) return limited

  let text = ""
  try { text = String((await req.json()).text ?? "") } catch { /* below */ }
  text = text.trim().slice(0, 20_000)
  if (!text) return jsonError(400, "bad_request", "Nothing to say.")

  let res: Response
  try {
    res = await upstream("/voice/speak", who.userId, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }),
    }, { timeoutMs: 55_000, signal: req.signal })
  } catch (e) {
    if (e instanceof UpstreamError) return jsonError(e.status, e.code, e.message)
    throw e
  }
  if (!res.ok || !res.body) return relayUpstreamError(res)
  return new Response(res.body, { status: 200, headers: { "Content-Type": "audio/mpeg", "Cache-Control": "no-store" } })
}
