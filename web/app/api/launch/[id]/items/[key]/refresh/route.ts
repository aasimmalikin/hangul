import { jsonError } from "@/lib/bff"
import { idOr400, userProxy } from "../../../../../_user"

export const runtime = "nodejs"

/** Search one item's price again (Plus; a few per plan). */
export async function POST(req: Request, { params }: { params: Promise<{ id: string; key: string }> }) {
  const { id, key } = await params
  if (!/^[a-z0-9_]{1,32}$/.test(key)) return jsonError(400, "bad_request", "Invalid item.")
  return idOr400(id) ?? userProxy(req, `/launch/${id}/items/${key}/refresh`, { method: "POST" })
}
