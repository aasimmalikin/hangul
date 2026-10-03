import { adminProxy } from "../_shared"

export const runtime = "nodejs"

/** Why people opened "Cancel plan" and how many stayed (last 90 days). */
export async function GET(req: Request) {
  return adminProxy(req, "/admin/churn", { method: "GET" })
}
