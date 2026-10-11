import { userProxy } from "../_user"

export const runtime = "nodejs"

/** The user's brands with `{slots, used, can_add}`. */
export async function GET(req: Request) { return userProxy(req, "/brands", { method: "GET" }) }

/** `{name, look?, kind?, colors?, style?, voice?, font?}` -> the new brand; 402 `brand_limit` when every slot is used. */
export async function POST(req: Request) { return userProxy(req, "/brands", { method: "POST", body: await req.text() }) }
