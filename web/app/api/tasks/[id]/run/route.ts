import { idOr400, userProxy } from "../../../_user"

export const runtime = "nodejs"

/** Run the task now (a real model run; the backend answers when it is done). */
export async function POST(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  return idOr400(id) ?? userProxy(req, `/tasks/${id}/run`, { method: "POST" })
}
