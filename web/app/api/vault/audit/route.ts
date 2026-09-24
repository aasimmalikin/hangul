import { vaultProxy } from "../_shared"

export const runtime = "nodejs"

/** The user's recent proxied calls: provider, method, path, status — never a body. */
export async function GET(req: Request) {
  return vaultProxy(req, "/vault/audit?limit=50", { method: "GET" })
}
