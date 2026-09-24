import { idOr400, userProxy } from "../../_user"

export const runtime = "nodejs"

export async function DELETE(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  return idOr400(id) ?? userProxy(req, `/tasks/${id}`, { method: "DELETE" })
}

/** Enable/disable: POST { enabled: boolean }. */
export async function POST(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  const bad = idOr400(id)
  if (bad) return bad
  let enabled = true
  try { enabled = Boolean((await req.json()).enabled) } catch { /* default */ }
  return userProxy(req, `/tasks/${id}/enabled?enabled=${enabled}`, { method: "POST" })
}
