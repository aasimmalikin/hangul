import { userProxy } from "../../_user"

export const runtime = "nodejs"

/** The "Before you go" choice: POST `{reason, detail, action: keep|downgrade|cancel}`. */
export async function POST(req: Request) { return userProxy(req, "/billing/leave", { method: "POST", body: await req.text() }) }
