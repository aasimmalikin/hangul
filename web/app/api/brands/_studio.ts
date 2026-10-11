import { assertSameOrigin, jsonError, rateLimit, relayUpstreamError, requireUser, upstream, UpstreamError } from "@/lib/bff"

/**
 * The Brand Studio's relay: like `_user.ts::userProxy`, plus binary answers
 * (the live preview JPEG, a post's ZIP), multipart uploads, and a timeout per
 * route (rendering every size or writing captions takes longer than 15 s).
 */
export async function studio(req: Request, path: string, opts: {
  method: "GET" | "POST" | "PATCH" | "DELETE"
  body?: BodyInit
  json?: boolean               // body is JSON text
  binary?: boolean             // pass the answer's bytes through (images, zips)
  timeoutMs?: number
  bucket?: string              // rate-limit area (default "brands")
  perMinute?: number
}): Promise<Response> {
  if (opts.method !== "GET") {
    const blocked = assertSameOrigin(req)
    if (blocked) return blocked
  }
  const who = await requireUser()
  if (who instanceof Response) return who
  const limited = rateLimit(`user:${opts.bucket ?? "brands"}:${who.userId}`, opts.perMinute ?? 60, 60_000)
  if (limited) return limited
  let res: Response
  try {
    res = await upstream(path, who.userId, {
      method: opts.method, body: opts.body, cache: "no-store",
      headers: opts.json ? { "Content-Type": "application/json" } : undefined,
    }, { timeoutMs: opts.timeoutMs ?? 15_000, signal: req.signal })
  } catch (e) {
    if (e instanceof UpstreamError) return jsonError(e.status, e.code, e.message)
    throw e
  }
  if (!res.ok) return relayUpstreamError(res)
  if (opts.binary && res.body) {
    const headers: Record<string, string> = { "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff" }
    for (const h of ["content-type", "content-disposition", "content-length"]) {
      const v = res.headers.get(h)
      if (v) headers[h] = v
    }
    return new Response(res.body, { status: 200, headers })
  }
  return new Response(await res.text(), { status: res.status, headers: { "Content-Type": "application/json", "Cache-Control": "private, no-store" } })
}

/** A multipart upload with one `file`, checked here so a huge file never crosses. */
export async function oneFile(req: Request, maxBytes: number, allowed: Set<string>, what: string): Promise<FormData | Response> {
  if (Number(req.headers.get("content-length") ?? 0) > maxBytes + 4096) return jsonError(413, "bad_request", `${what} can be up to ${Math.round(maxBytes / 1048576)} MB.`)
  let incoming: FormData
  try {
    incoming = await req.formData()
  } catch {
    return jsonError(400, "bad_request", "Malformed upload.")
  }
  const file = incoming.get("file")
  if (!(file instanceof File) || file.size === 0) return jsonError(400, "bad_request", "No file provided.")
  const name = file.name.replace(/[/\\]/g, "_").slice(0, 200) || "photo.jpg"
  const ext = name.includes(".") ? "." + name.split(".").pop()!.toLowerCase() : ""
  if (!allowed.has(ext)) return jsonError(400, "bad_request", `Upload ${what.toLowerCase()} as JPG, PNG or WebP.`)
  if (file.size > maxBytes) return jsonError(413, "bad_request", `${what} can be up to ${Math.round(maxBytes / 1048576)} MB.`)
  const form = new FormData()
  form.append("file", file, name)
  return form
}

export const PHOTO_TYPES = new Set([".png", ".jpg", ".jpeg", ".webp", ".heic", ".heif"])
export const idOk = (id: string) => /^\d{1,10}$/.test(id)
