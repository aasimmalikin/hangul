import { jsonError } from "@/lib/bff"
import { adminProxy } from "../../../_shared"

export const runtime = "nodejs"

/** One stored report, with per-case scores and trajectories. */
export async function GET(req: Request, { params }: { params: Promise<{ file: string }> }) {
  const { file } = await params
  if (!/^[a-z_]+-\d{8}-\d{6}\.json$/.test(file)) return jsonError(400, "bad_request", "Invalid report name.")
  return adminProxy(req, `/admin/evals/runs/${file}`, { method: "GET" })
}
