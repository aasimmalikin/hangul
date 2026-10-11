import { jsonError } from "@/lib/bff"
import { userProxy } from "../../_user"

export const runtime = "nodejs"

/** One month's outcome report (`?month=YYYY-MM`). */
export async function GET(req: Request) {
  const month = new URL(req.url).searchParams.get("month") ?? ""
  if (!/^\d{4}-\d{2}$/.test(month)) return jsonError(400, "bad_request", "month must be YYYY-MM")
  return userProxy(req, `/missions/report?month=${month}`, { method: "GET" })
}
