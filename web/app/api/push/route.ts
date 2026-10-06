import { userProxy } from "../_user"

export const runtime = "nodejs"

/** GET: are notifications set up, the server's public key, and is this device (?endpoint=) on. */
export async function GET(req: Request) {
  const endpoint = new URL(req.url).searchParams.get("endpoint")
  return userProxy(req, endpoint ? `/push?endpoint=${encodeURIComponent(endpoint.slice(0, 1024))}` : "/push", { method: "GET" })
}
