import { jsonError } from "@/lib/bff"
import { idOr400, userProxy } from "../../../_user"

export const runtime = "nodejs"

/** `{decision: "approve" | "reject"}`: the owner's go-ahead. 409 once decided or expired, 402 off Pro. */
export async function POST(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  const body = await req.json().catch(() => null)
  if (!body || (body.decision !== "approve" && body.decision !== "reject")) return jsonError(400, "bad_request", "Invalid decision.")
  return idOr400(id) ?? userProxy(req, `/missions/${id}/decide`, { method: "POST", body: JSON.stringify({ decision: body.decision }) })
}
