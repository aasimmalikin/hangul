import { idOr400, userProxy } from "../../../_user"

export const runtime = "nodejs"

/** Tick / untick: PATCH `{done: boolean}`. */
export async function PATCH(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  const bad = idOr400(id)
  if (bad) return bad
  let done = true
  try { done = Boolean((await req.json()).done) } catch { /* default */ }
  return userProxy(req, `/lists/items/${id}`, { method: "PATCH", body: JSON.stringify({ done }) })
}

export async function DELETE(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  return idOr400(id) ?? userProxy(req, `/lists/items/${id}`, { method: "DELETE" })
}
