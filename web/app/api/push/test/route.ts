import { userProxy } from "../../_user"

export const runtime = "nodejs"

/** POST: send "notifications are on" to every device the user turned them on for. */
export async function POST(req: Request) { return userProxy(req, "/push/test", { method: "POST" }) }
