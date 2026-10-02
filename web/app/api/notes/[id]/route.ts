import { idOr400, userProxy } from "../../_user"

export const runtime = "nodejs"

export async function DELETE(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  return idOr400(id) ?? userProxy(req, `/notes/${id}`, { method: "DELETE" })
}
