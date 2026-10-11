import { jsonError } from "@/lib/bff"
import { idOk, oneFile, PHOTO_TYPES, studio } from "../../_studio"

export const runtime = "nodejs"
export const maxDuration = 60

/** The brand's photo library. */
export async function GET(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  return idOk(id) ? studio(req, `/brands/${id}/assets`, { method: "GET" }) : jsonError(400, "bad_request", "Invalid id.")
}

/** Add one photo (the page uploads several one after another). */
export async function POST(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  if (!idOk(id)) return jsonError(400, "bad_request", "Invalid id.")
  const form = await oneFile(req, 15 * 1024 * 1024, PHOTO_TYPES, "A photo")
  if (form instanceof Response) return form
  return studio(req, `/brands/${id}/assets`, { method: "POST", body: form, timeoutMs: 45_000, bucket: "brands-upload", perMinute: 40 })
}
