import { userProxy } from "../_user"

export const runtime = "nodejs"

/** The user's files, newest first: uploads, created documents, charts, images, voice notes. */
export async function GET(req: Request) { return userProxy(req, "/files", { method: "GET" }) }
