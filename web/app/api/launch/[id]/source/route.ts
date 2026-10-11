import { idOr400, userProxy } from "../../../_user"

export const runtime = "nodejs"

/** Search live prices for a plan made with estimates (402 when the plan doesn't include it). */
export async function POST(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  return idOr400(id) ?? userProxy(req, `/launch/${id}/source`, { method: "POST" })
}
