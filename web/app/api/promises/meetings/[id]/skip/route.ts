import { jsonError } from "@/lib/bff"
import { userProxy } from "../../../../_user"

export const runtime = "nodejs"

/** "Nothing was promised": stop asking about that meeting. */
export async function POST(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  if (!/^[\w-]{1,200}$/.test(id)) return jsonError(400, "bad_request", "Invalid meeting.")
  return userProxy(req, `/promises/meetings/${id}/skip`, { method: "POST", body: "{}" })
}
