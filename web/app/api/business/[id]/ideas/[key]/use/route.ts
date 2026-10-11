import { jsonError } from "@/lib/bff"
import { idOr400, userProxy } from "../../../../../_user"

export const runtime = "nodejs"

/** "Make this post": counts against Plus's weekly idea, and answers where Brand Studio opens with it. */
export async function POST(req: Request, { params }: { params: Promise<{ id: string; key: string }> }) {
  const { id, key } = await params
  if (!/^[a-z0-9_]{1,40}$/.test(key)) return jsonError(400, "bad_request", "Invalid idea.")
  return idOr400(id) ?? userProxy(req, `/business/${id}/ideas/${key}/use`, { method: "POST" })
}
