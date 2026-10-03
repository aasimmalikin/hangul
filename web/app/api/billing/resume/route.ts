import { userProxy } from "../../_user"

export const runtime = "nodejs"

/** Undo a cancellation before the period ends. */
export async function POST(req: Request) { return userProxy(req, "/billing/resume", { method: "POST" }) }
