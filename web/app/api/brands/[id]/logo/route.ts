import { assertSameOrigin, jsonError, rateLimit, relayUpstreamError, requireUser, upstream, UpstreamError } from "@/lib/bff"
import { idOr400 } from "../../../_user"

export const runtime = "nodejs"

// Mirrors harness.api.routes.brands.LOGO_MAX_BYTES.
const MAX_BYTES = 5 * 1024 * 1024
const ALLOWED = new Set([".png", ".jpg", ".jpeg", ".webp"])

/** A brand's logo: stored as a PNG, answered with the colours it suggests. */
export async function POST(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  const bad = idOr400(id)
  if (bad) return bad
  const blocked = assertSameOrigin(req)
  if (blocked) return blocked
  const who = await requireUser()
  if (who instanceof Response) return who
  const limited = rateLimit(`user:brands-logo:${who.userId}`, 10, 60_000)
  if (limited) return limited
  if (Number(req.headers.get("content-length") ?? 0) > MAX_BYTES + 4096) return jsonError(413, "bad_request", "A logo can be up to 5 MB.")

  let incoming: FormData
  try {
    incoming = await req.formData()
  } catch {
    return jsonError(400, "bad_request", "Malformed upload.")
  }
  const file = incoming.get("file")
  if (!(file instanceof File) || file.size === 0) return jsonError(400, "bad_request", "No file provided.")
  const name = file.name.replace(/[/\\]/g, "_").slice(0, 200) || "logo.png"
  const ext = name.includes(".") ? "." + name.split(".").pop()!.toLowerCase() : ""
  if (!ALLOWED.has(ext)) return jsonError(400, "bad_request", "Upload the logo as PNG, JPG or WebP.")
  if (file.size > MAX_BYTES) return jsonError(413, "bad_request", "A logo can be up to 5 MB.")

  const form = new FormData()
  form.append("file", file, name)
  let res: Response
  try {
    const variant = new URL(req.url).searchParams.get("variant") === "dark" ? "?variant=dark" : ""
    res = await upstream(`/brands/${id}/logo${variant}`, who.userId, { method: "POST", body: form }, { timeoutMs: 30_000, signal: req.signal })
  } catch (e) {
    if (e instanceof UpstreamError) return jsonError(e.status, e.code, e.message)
    throw e
  }
  if (!res.ok) return relayUpstreamError(res)
  return new Response(await res.text(), { status: 200, headers: { "Content-Type": "application/json", "Cache-Control": "private, no-store" } })
}
