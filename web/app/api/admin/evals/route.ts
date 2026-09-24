import { adminProxy } from "../_shared"

export const runtime = "nodejs"

/** Catalog (available + planned evals), latest-per-suite summary, run status and stored runs, by `view`. */
export async function GET(req: Request) {
  const url = new URL(req.url)
  const view = url.searchParams.get("view") ?? "summary"
  if (view === "catalog") return adminProxy(req, "/admin/evals/catalog", { method: "GET" })
  if (view === "status") return adminProxy(req, "/admin/evals/status", { method: "GET" })
  if (view === "runs") {
    const suite = url.searchParams.get("suite")
    const qs = suite && /^[a-z_]+$/.test(suite) ? `?suite=${suite}&limit=30` : "?limit=30"
    return adminProxy(req, `/admin/evals/runs${qs}`, { method: "GET" })
  }
  return adminProxy(req, "/admin/evals/summary", { method: "GET" })
}
