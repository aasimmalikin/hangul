import { userProxy } from "../_user"

export const runtime = "nodejs"

/** The user's launch plans, newest first (summaries). */
export async function GET(req: Request) { return userProxy(req, "/launch", { method: "GET" }) }

/** `{kind, city, area?, size, renting?, budget?, start?, note?, live?}` -> `{plan, access}`. Live prices are
 * searched in the background when the plan allows; otherwise `access` says why and the plan uses estimates. */
export async function POST(req: Request) { return userProxy(req, "/launch", { method: "POST", body: await req.text() }) }
