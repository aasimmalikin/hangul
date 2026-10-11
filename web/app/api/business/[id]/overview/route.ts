import { jsonError } from "@/lib/bff"
import { idOk, studio } from "../../../brands/_studio"

export const runtime = "nodejs"

/** The week, history, tomorrow's forecast and slow-day ideas (what the plan includes). Weather lookups can take a few seconds. */
export async function GET(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  return idOk(id) ? studio(req, `/business/${id}/overview`, { method: "GET", timeoutMs: 25_000, bucket: "business" })
    : jsonError(400, "bad_request", "Invalid id.")
}
