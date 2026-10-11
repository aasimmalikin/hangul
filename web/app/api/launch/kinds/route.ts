import { userProxy } from "../../_user"

export const runtime = "nodejs"

/** The kinds of business a plan covers (with their sizes), and whether this user gets live prices. */
export async function GET(req: Request) { return userProxy(req, "/launch/kinds", { method: "GET" }) }
