import { userProxy } from "../_user"

export const runtime = "nodejs"

/** The home screen's brief: weather, today's calendar, reminders, to-dos, approvals waiting, important mail.
 *  `?quick=1` is the instant part only (database + cache), drawn while the full brief loads. */
export async function GET(req: Request) {
  const quick = new URL(req.url).searchParams.get("quick") === "1"
  return userProxy(req, quick ? "/today?quick=1" : "/today", { method: "GET" })
}
