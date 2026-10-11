import { jsonError } from "@/lib/bff"
import { idOk, studio } from "../../_studio"

export const runtime = "nodejs"
export const maxDuration = 120

export async function GET(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  return idOk(id) ? studio(req, `/brands/${id}/posts`, { method: "GET" }) : jsonError(400, "bad_request", "Invalid id.")
}

/** Render every size (or every carousel slide) and keep the post. */
export async function POST(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  if (!idOk(id)) return jsonError(400, "bad_request", "Invalid id.")
  const body = await req.text()
  if (body.length > 20_000) return jsonError(413, "bad_request", "That design is too large.")
  return studio(req, `/brands/${id}/posts`, { method: "POST", body, json: true, timeoutMs: 110_000, bucket: "brands-render", perMinute: 20 })
}
