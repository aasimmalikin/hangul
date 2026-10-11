import { jsonError } from "@/lib/bff"
import { userProxy } from "../../_user"

export const runtime = "nodejs"

/** `{email_on}`: whether Hangul reads the user's email for promises. */
export async function PUT(req: Request) {
  const body = await req.json().catch(() => null)
  if (typeof body?.email_on !== "boolean") return jsonError(400, "bad_request", "Invalid setting.")
  return userProxy(req, "/promises/settings", { method: "PUT", body: JSON.stringify({ email_on: body.email_on }) })
}
