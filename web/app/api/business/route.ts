import { userProxy } from "../_user"

export const runtime = "nodejs"

/** The user's businesses with `{slots, can_add, access, kinds}`. */
export async function GET(req: Request) { return userProxy(req, "/business", { method: "GET" }) }

/** `{name, kind, city, brand_id?, launch_plan_id?, nudges?}`; 402 `business_limit` past the plan's count. */
export async function POST(req: Request) { return userProxy(req, "/business", { method: "POST", body: await req.text() }) }
