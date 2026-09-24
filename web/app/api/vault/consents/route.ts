import { vaultProxy } from "../_shared"

export const runtime = "nodejs"

export async function GET(req: Request) {
  return vaultProxy(req, "/vault/consents", { method: "GET" })
}

/** Grant the agent standing permission to use a provider for a while. */
export async function POST(req: Request) {
  return vaultProxy(req, "/vault/consents", { method: "POST", body: await req.text() })
}
