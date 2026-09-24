import { idOr400, vaultProxy } from "../../_shared"

export const runtime = "nodejs"

export async function DELETE(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  const bad = idOr400(id, "consent")
  if (bad) return bad
  return vaultProxy(req, `/vault/consents/${id}`, { method: "DELETE" })
}
