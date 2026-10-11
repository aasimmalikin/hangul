import { idOr400, userProxy } from "../../../_user"

export const runtime = "nodejs"

/** The chat message that asks for a follow-up draft to someone who owes the user. 402 on Free. */
export async function POST(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  return idOr400(id) ?? userProxy(req, `/promises/${id}/chase`, { method: "POST", body: "{}" })
}
