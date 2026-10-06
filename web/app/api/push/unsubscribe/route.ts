import { jsonError } from "@/lib/bff"
import { userProxy } from "../../_user"

export const runtime = "nodejs"

/** POST {endpoint}: turn notifications off on this device. */
export async function POST(req: Request) {
  const body = await req.text()
  if (body.length > 2048) return jsonError(413, "bad_request", "Request too large.")
  return userProxy(req, "/push/unsubscribe", { method: "POST", body })
}
