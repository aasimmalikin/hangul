import { userProxy } from "../_user"

export const runtime = "nodejs"

/** The caller's plan, allowance left, credits and portal link (backend `GET /billing`). */
export async function GET(req: Request) { return userProxy(req, "/billing", { method: "GET" }) }
