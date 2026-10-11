import { jsonError } from "@/lib/bff"
import { idOk, studio } from "../../../_studio"

export const runtime = "nodejs"

export async function DELETE(req: Request, { params }: { params: Promise<{ id: string; aid: string }> }) {
  const { id, aid } = await params
  return idOk(id) && idOk(aid) ? studio(req, `/brands/${id}/assets/${aid}`, { method: "DELETE" }) : jsonError(400, "bad_request", "Invalid id.")
}
