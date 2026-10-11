import { idOr400, userProxy } from "../../_user"

export const runtime = "nodejs"

export async function PATCH(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  return idOr400(id) ?? userProxy(req, `/customers/${id}`, { method: "PATCH", body: await req.text() })
}

/** Takes them off the list (hidden, not deleted). */
export async function DELETE(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  return idOr400(id) ?? userProxy(req, `/customers/${id}`, { method: "DELETE" })
}
