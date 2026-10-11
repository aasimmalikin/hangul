import { idOr400, userProxy } from "../../../_user"

export const runtime = "nodejs"

/** They came in today (counted once a day). */
export async function POST(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  return idOr400(id) ?? userProxy(req, `/customers/${id}/visit`, { method: "POST" })
}
