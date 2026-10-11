import { jsonError } from "@/lib/bff"
import { idOr400, userProxy } from "../../../_user"

export const runtime = "nodejs"

/** `{auto: boolean}`: let Hangul go ahead on slow days for this business without asking. */
export async function PUT(req: Request, { params }: { params: Promise<{ businessId: string }> }) {
  const { businessId } = await params
  const body = await req.json().catch(() => null)
  if (!body || typeof body.auto !== "boolean") return jsonError(400, "bad_request", "auto must be true or false")
  return idOr400(businessId) ?? userProxy(req, `/missions/trust/${businessId}`, { method: "PUT", body: JSON.stringify({ auto: body.auto }) })
}
