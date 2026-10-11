import { jsonError } from "@/lib/bff"
import { idOr400, userProxy } from "../../../../_user"

export const runtime = "nodejs"

export async function DELETE(req: Request, { params }: { params: Promise<{ id: string; day: string }> }) {
  const { id, day } = await params
  if (!/^\d{4}-\d{2}-\d{2}$/.test(day)) return jsonError(400, "bad_request", "Invalid day.")
  return idOr400(id) ?? userProxy(req, `/business/${id}/days/${day}`, { method: "DELETE" })
}
