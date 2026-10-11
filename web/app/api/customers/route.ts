import { userProxy } from "../_user"

export const runtime = "nodejs"

/** The shop's customers (`?q=` searches) with `{total, birthdays, lapsed, today}`. */
export async function GET(req: Request) {
  const q = new URL(req.url).searchParams.get("q") ?? ""
  return userProxy(req, `/customers${q ? `?q=${encodeURIComponent(q.slice(0, 80))}` : ""}`, { method: "GET" })
}

/** `{name, phone?, birthday?, note?}`; the same phone (or name) updates the one already there. */
export async function POST(req: Request) { return userProxy(req, "/customers", { method: "POST", body: await req.text() }) }
