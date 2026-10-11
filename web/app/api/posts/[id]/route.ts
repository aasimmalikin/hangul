import { jsonError } from "@/lib/bff"
import { idOk, studio } from "../../brands/_studio"

export const runtime = "nodejs"

export async function DELETE(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  return idOk(id) ? studio(req, `/posts/${id}`, { method: "DELETE" }) : jsonError(400, "bad_request", "Invalid id.")
}
