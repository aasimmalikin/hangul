import { jsonError } from "@/lib/bff"
import { userProxy } from "../../_user"

export const runtime = "nodejs"

const MOODS = new Set(["great", "ok", "tired", "busy"])

/** The morning check-in on Today: POST { mood }. Answers with Hangul's reply and the streak. */
export async function POST(req: Request) {
  let mood = ""
  try { mood = String((await req.json()).mood ?? "") } catch { /* fall through */ }
  if (!MOODS.has(mood)) return jsonError(400, "bad_request", "Pick one of: great, ok, tired, busy.")
  return userProxy(req, "/today/checkin", { method: "POST", body: JSON.stringify({ mood }) })
}
