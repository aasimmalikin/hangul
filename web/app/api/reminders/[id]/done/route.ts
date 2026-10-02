import { idOr400, userProxy } from "../../../_user"

export const runtime = "nodejs"

/** Dismiss a fired reminder (the bell's "Done"). */
export async function POST(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  return idOr400(id) ?? userProxy(req, `/reminders/${id}/done`, { method: "POST" })
}
