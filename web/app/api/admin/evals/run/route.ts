import { adminProxy } from "../../_shared"

export const runtime = "nodejs"

/** Start a suite in the background on the backend. Costs real model calls, hence POST + same-origin + admin. */
export async function POST(req: Request) {
  return adminProxy(req, "/admin/evals/run", { method: "POST", body: await req.text() })
}
