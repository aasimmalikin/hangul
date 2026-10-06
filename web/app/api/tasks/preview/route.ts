import { userProxy } from "../../_user"

export const runtime = "nodejs"

/** What the task form shows as you type: apps the words switch on, what may be pre-approved, a title. */
export async function POST(req: Request) { return userProxy(req, "/tasks/preview", { method: "POST", body: await req.text() }) }
