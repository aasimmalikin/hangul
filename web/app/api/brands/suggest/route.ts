import { userProxy } from "../../_user"

export const runtime = "nodejs"

/** `{sentence}` -> `{kind, label, name, looks[3]}` for the setup screen. */
export async function POST(req: Request) { return userProxy(req, "/brands/suggest", { method: "POST", body: await req.text() }) }
