import { userProxy } from "../_user"

export const runtime = "nodejs"

/** Notes, newest first; `?q=` filters by words. */
export async function GET(req: Request) {
  const q = (new URL(req.url).searchParams.get("q") ?? "").slice(0, 200)
  return userProxy(req, `/notes?q=${encodeURIComponent(q)}`, { method: "GET" })
}
