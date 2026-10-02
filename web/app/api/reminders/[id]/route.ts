import { idOr400, userProxy } from "../../_user"

export const runtime = "nodejs"

/** Cancel a reminder. */
export async function DELETE(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  return idOr400(id) ?? userProxy(req, `/reminders/${id}`, { method: "DELETE" })
}
