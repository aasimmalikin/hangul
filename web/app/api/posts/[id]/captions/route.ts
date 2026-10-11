import { jsonError } from "@/lib/bff"
import { idOk, studio } from "../../../brands/_studio"

export const runtime = "nodejs"
export const maxDuration = 90

/** `{platforms, note}`: captions per platform in the brand's voice (a cheap-model call). */
export async function POST(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  if (!idOk(id)) return jsonError(400, "bad_request", "Invalid id.")
  return studio(req, `/posts/${id}/captions`, { method: "POST", body: (await req.text()).slice(0, 4000), json: true, timeoutMs: 80_000, bucket: "brands-captions", perMinute: 20 })
}

/** `{platform, text, hashtags, first_comment}`: the user's own edit. */
export async function PATCH(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  if (!idOk(id)) return jsonError(400, "bad_request", "Invalid id.")
  const body = await req.text()
  if (body.length > 12_000) return jsonError(413, "bad_request", "That caption is too long.")
  return studio(req, `/posts/${id}/captions`, { method: "PATCH", body, json: true })
}
