import { adminProxy } from "../_shared"

export const runtime = "nodejs"

/** Pre-registrations (/join): total, last 7 days, by persona, plan interest and source. */
export async function GET(req: Request) {
  return adminProxy(req, "/admin/waitlist", { method: "GET" })
}
