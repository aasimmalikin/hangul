import { idOr400, userProxy } from "../../../_user"

export const runtime = "nodejs"

/** Take back a go-ahead before the day is over (and go back to asking first). */
export async function POST(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  return idOr400(id) ?? userProxy(req, `/missions/${id}/undo`, { method: "POST" })
}
