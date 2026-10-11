import { userProxy } from "../_user"

export const runtime = "nodejs"

/** The jobs Hangul is carrying through, the trust given per business, and this and last month's results. */
export async function GET(req: Request) { return userProxy(req, "/missions", { method: "GET" }) }
