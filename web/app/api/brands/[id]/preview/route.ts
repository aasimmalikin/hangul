import { jsonError } from "@/lib/bff"
import { idOk, studio } from "../../_studio"

export const runtime = "nodejs"

/** The live preview: a small JPEG of the design (free; no AI). Its own, roomier rate limit. */
export async function POST(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  if (!idOk(id)) return jsonError(400, "bad_request", "Invalid id.")
  const body = await req.text()
  if (body.length > 20_000) return jsonError(413, "bad_request", "That design is too large.")
  return studio(req, `/brands/${id}/preview`, { method: "POST", body, json: true, binary: true, bucket: "brands-preview", perMinute: 240, timeoutMs: 20_000 })
}
