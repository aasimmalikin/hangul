import { idOr400, userProxy } from "../../_user"

export const runtime = "nodejs"

export async function PATCH(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  return idOr400(id) ?? userProxy(req, `/brands/${id}`, { method: "PATCH", body: await req.text() })
}

/** Hides the brand and frees its slot. */
export async function DELETE(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  return idOr400(id) ?? userProxy(req, `/brands/${id}`, { method: "DELETE" })
}
