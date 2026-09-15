import { assertSameOrigin, jsonError, rateLimit, relayUpstreamError, requireUser, upstream, UpstreamError } from "@/lib/bff"

export const runtime = "nodejs"
export const maxDuration = 120

// Mirrors harness.retrieval.upload_ingest: refuse here so a 50 MB video
// never crosses the wire to the backend.
const MAX_BYTES = 10 * 1024 * 1024
const ALLOWED = new Set([".pdf", ".txt", ".md"])

/**
 * Relays a document upload to the backend, which chunks and embeds it into
 * the caller's per-user session index so `search_docs` can find it.
 */
export async function POST(req: Request) {
  const blocked = assertSameOrigin(req)
  if (blocked) return blocked
  const who = await requireUser()
  if (who instanceof Response) return who
  const limited = rateLimit(`upload:${who.userId}`, 10, 60_000)
  if (limited) return limited

  const declared = Number(req.headers.get("content-length") ?? 0)
  if (declared > MAX_BYTES + 4096) {
    return jsonError(413, "bad_request", "That file is larger than 10 MB.")
  }

  let incoming: FormData
  try {
    incoming = await req.formData()
  } catch {
    return jsonError(400, "bad_request", "Malformed upload.")
  }
  const file = incoming.get("file")
  if (!(file instanceof File)) return jsonError(400, "bad_request", "No file provided.")

  const name = file.name.replace(/[/\\]/g, "_").slice(0, 200) || "upload"
  const ext = name.includes(".") ? "." + name.split(".").pop()!.toLowerCase() : ""
  if (!ALLOWED.has(ext)) return jsonError(400, "bad_request", "Only PDF, TXT and MD files are supported.")
  if (file.size === 0) return jsonError(400, "bad_request", "That file is empty.")
  if (file.size > MAX_BYTES) return jsonError(413, "bad_request", "That file is larger than 10 MB.")

  const form = new FormData()
  form.append("file", file, name)

  let res: Response
  try {
    res = await upstream("/upload", who.userId, { method: "POST", body: form }, { timeoutMs: 110_000, signal: req.signal })
  } catch (e) {
    if (e instanceof UpstreamError) return jsonError(e.status, e.code, e.message)
    throw e
  }
  if (!res.ok) return relayUpstreamError(res)

  return new Response(await res.text(), { status: 200, headers: { "Content-Type": "application/json" } })
}
