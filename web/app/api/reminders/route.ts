import { userProxy } from "../_user"

export const runtime = "nodejs"

/** `?scope=upcoming|due|open` — the bell polls `due` (fired, not yet dismissed). */
export async function GET(req: Request) {
  const scope = new URL(req.url).searchParams.get("scope") ?? "upcoming"
  if (!["upcoming", "due", "open"].includes(scope)) return Response.json({ detail: "bad scope", code: "bad_request" }, { status: 400 })
  return userProxy(req, `/reminders?scope=${scope}`, { method: "GET" })
}
