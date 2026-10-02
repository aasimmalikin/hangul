import { userProxy } from "../_user"

export const runtime = "nodejs"

/** The user's lists, grouped by name: `{lists: {"Shopping": [...]}}`. */
export async function GET(req: Request) {
  const done = new URL(req.url).searchParams.get("include_done") === "true"
  return userProxy(req, `/lists?include_done=${done}`, { method: "GET" })
}

/** Add an item: POST `{list, text}`. */
export async function POST(req: Request) { return userProxy(req, "/lists", { method: "POST", body: await req.text() }) }
