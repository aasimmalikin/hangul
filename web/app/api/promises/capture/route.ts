import { jsonError } from "@/lib/bff"
import { userProxy } from "../../_user"

export const runtime = "nodejs"

/** `{text, meeting_id?}`: the answer to "was anything promised?" after a meeting. 402 on Free. */
export async function POST(req: Request) {
  const body = await req.json().catch(() => null)
  const text = typeof body?.text === "string" ? body.text.trim().slice(0, 2000) : ""
  if (!text) return jsonError(400, "bad_request", "Say what was promised.")
  const meeting_id = typeof body?.meeting_id === "string" ? body.meeting_id.slice(0, 200) : null
  return userProxy(req, "/promises/capture", { method: "POST", body: JSON.stringify({ text, meeting_id }) })
}
