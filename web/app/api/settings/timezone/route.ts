import { jsonError } from "@/lib/bff"
import { timeZoneOrUndefined } from "@/lib/timezone"
import { userProxy } from "../../_user"

export const runtime = "nodejs"

/** The device's timezone, reported on page load: POST `{timezone}`. */
export async function POST(req: Request) {
  let timezone: string | undefined
  try { timezone = timeZoneOrUndefined((await req.json()).timezone) } catch { /* below */ }
  if (!timezone) return jsonError(400, "bad_request", "Invalid timezone.")
  return userProxy(req, "/settings/timezone", { method: "POST", body: JSON.stringify({ timezone }) })
}
