import { userProxy } from "../_user"

export const runtime = "nodejs"

/** Personalisation: name, tone, timezone, custom instructions. */
export async function GET(req: Request) { return userProxy(req, "/settings", { method: "GET" }) }
export async function PUT(req: Request) { return userProxy(req, "/settings", { method: "PUT", body: await req.text() }) }
