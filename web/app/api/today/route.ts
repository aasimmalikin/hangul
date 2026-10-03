import { userProxy } from "../_user"

export const runtime = "nodejs"

/** The home screen's brief: weather, today's calendar, reminders, to-dos, approvals waiting, important mail. */
export async function GET(req: Request) { return userProxy(req, "/today", { method: "GET" }) }
