import { adminProxy } from "../_shared"

export const runtime = "nodejs"

/** Live metrics and recent traces from the backend's ring buffer. */
export async function GET(req: Request) {
  return adminProxy(req, "/admin/overview", { method: "GET" })
}
