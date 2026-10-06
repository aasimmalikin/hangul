import { userProxy } from "../../_user"

export const runtime = "nodejs"

/** The Kept tab's badge: approvals waiting on the user. */
export async function GET(req: Request) {
  return userProxy(req, "/kept/count", { method: "GET" })
}
