import { userProxy } from "../_user"

export const runtime = "nodejs"

/** The Kept tab: everything the user asked Hangul to do, in their words. `?q=` searches all time. */
export async function GET(req: Request) {
  const q = (new URL(req.url).searchParams.get("q") ?? "").slice(0, 200)
  return userProxy(req, q ? `/kept?q=${encodeURIComponent(q)}` : "/kept", { method: "GET" })
}
