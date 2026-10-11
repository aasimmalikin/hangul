import { userProxy } from "../../_user"

export const runtime = "nodejs"

/** The template library: kinds, three looks each, and the font keys. */
export async function GET(req: Request) { return userProxy(req, "/brands/templates", { method: "GET" }) }
