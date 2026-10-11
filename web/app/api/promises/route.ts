import { jsonError } from "@/lib/bff"
import { userProxy } from "../_user"

export const runtime = "nodejs"

const STATUSES = new Set(["open", "done", "dropped", "all"])

/** Kept your word: open promises (`?status=` done | dropped | all), counts, plan access, the email switch,
 * and meetings Hangul just asked about. */
export async function GET(req: Request) {
  const status = new URL(req.url).searchParams.get("status") ?? "open"
  if (!STATUSES.has(status)) return jsonError(400, "bad_request", "Invalid status.")
  return userProxy(req, `/promises?status=${status}`, { method: "GET" })
}

/** `{direction: "mine" | "theirs", what, who?, who_email?, due_on?}`: keep a promise by hand. */
export async function POST(req: Request) {
  const body = await req.json().catch(() => null)
  if (!body || (body.direction !== "mine" && body.direction !== "theirs") || typeof body.what !== "string" || !body.what.trim())
    return jsonError(400, "bad_request", "Say who promised and what.")
  const out = {
    direction: body.direction, what: String(body.what).slice(0, 300), who: String(body.who ?? "").slice(0, 120),
    who_email: String(body.who_email ?? "").slice(0, 255), due_on: typeof body.due_on === "string" && body.due_on ? body.due_on : null,
  }
  return userProxy(req, "/promises", { method: "POST", body: JSON.stringify(out) })
}
