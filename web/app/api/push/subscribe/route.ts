import { jsonError } from "@/lib/bff"
import { userProxy } from "../../_user"

export const runtime = "nodejs"

/** POST: this browser's PushSubscription (endpoint + keys); the backend checks it's a real push service. */
export async function POST(req: Request) {
  const body = await req.text()
  if (body.length > 4096) return jsonError(413, "bad_request", "Subscription too large.")
  return userProxy(req, "/push/subscribe", { method: "POST", body })
}
