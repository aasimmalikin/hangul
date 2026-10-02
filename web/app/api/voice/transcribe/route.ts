import { assertSameOrigin, jsonError, rateLimit, relayUpstreamError, requireUser, upstream, UpstreamError } from "@/lib/bff"

export const runtime = "nodejs"
export const maxDuration = 120

const MAX_BYTES = 10 * 1024 * 1024

/** Mic recording -> text (backend `POST /voice/transcribe`, metered). */
export async function POST(req: Request) {
  const blocked = assertSameOrigin(req)
  if (blocked) return blocked
  const who = await requireUser()
  if (who instanceof Response) return who
  const limited = rateLimit(`voice:${who.userId}`, 40, 60_000)
  if (limited) return limited
  if (Number(req.headers.get("content-length") ?? 0) > MAX_BYTES + 4096) {
    return jsonError(413, "bad_request", "That recording is too long.")
  }

  let incoming: FormData
  try { incoming = await req.formData() } catch { return jsonError(400, "bad_request", "Malformed upload.") }
  const file = incoming.get("file")
  if (!(file instanceof File) || file.size === 0) return jsonError(400, "bad_request", "No audio received.")
  if (file.size > MAX_BYTES) return jsonError(413, "bad_request", "That recording is too long.")
  const form = new FormData()
  form.append("file", file, file.name.replace(/[/\\]/g, "_").slice(0, 80) || "speech.webm")
  const seconds = Number(incoming.get("seconds"))
  if (Number.isFinite(seconds) && seconds > 0) form.append("seconds", String(Math.min(seconds, 900)))

  let res: Response
  try {
    res = await upstream("/voice/transcribe", who.userId, { method: "POST", body: form }, { timeoutMs: 110_000, signal: req.signal })
  } catch (e) {
    if (e instanceof UpstreamError) return jsonError(e.status, e.code, e.message)
    throw e
  }
  if (!res.ok) return relayUpstreamError(res)
  return new Response(await res.text(), { status: 200, headers: { "Content-Type": "application/json", "Cache-Control": "no-store" } })
}
