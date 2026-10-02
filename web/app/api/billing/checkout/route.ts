import { userProxy } from "../../_user"

export const runtime = "nodejs"

/** `{product: "plus"|"pro"|"topup"}` -> `{url}`: a Dodo Payments hosted checkout for this user. */
export async function POST(req: Request) { return userProxy(req, "/billing/checkout", { method: "POST", body: await req.text() }) }
