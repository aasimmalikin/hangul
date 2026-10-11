import { idOr400, userProxy } from "../../_user"

export const runtime = "nodejs"

/** One mission with its checklist; 404 when it isn't the user's. */
export async function GET(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  return idOr400(id) ?? userProxy(req, `/missions/${id}`, { method: "GET" })
}
