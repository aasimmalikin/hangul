import { userProxy } from "../_user"

export const runtime = "nodejs"

/** Scheduled tasks: list and create. */
export async function GET(req: Request) { return userProxy(req, "/tasks", { method: "GET" }) }
export async function POST(req: Request) { return userProxy(req, "/tasks", { method: "POST", body: await req.text() }) }
