import { adminProxy } from "../_shared"

export const runtime = "nodejs"

/** Prompt-injection events: counts by layer/severity/action and the newest rows (reasons only, never content). */
export async function GET(req: Request) {
  return adminProxy(req, "/admin/security?limit=60", { method: "GET" })
}
