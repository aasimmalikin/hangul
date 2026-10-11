import { jsonError } from "@/lib/bff"
import { idOr400, userProxy } from "../../_user"

export const runtime = "nodejs"

/** `{status?: "open" | "done" | "dropped", what?, who?, due_on?, clear_due?}`. 404 when it isn't the user's. */
export async function PATCH(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  const body = await req.json().catch(() => null)
  if (!body || typeof body !== "object") return jsonError(400, "bad_request", "Invalid body.")
  const out: Record<string, unknown> = {}
  if (["open", "done", "dropped"].includes(body.status)) out.status = body.status
  if (typeof body.what === "string" && body.what.trim()) out.what = body.what.slice(0, 300)
  if (typeof body.who === "string") out.who = body.who.slice(0, 120)
  if (typeof body.due_on === "string" && /^\d{4}-\d{2}-\d{2}$/.test(body.due_on)) out.due_on = body.due_on
  if (body.clear_due === true) out.clear_due = true
  return idOr400(id) ?? userProxy(req, `/promises/${id}`, { method: "PATCH", body: JSON.stringify(out) })
}
