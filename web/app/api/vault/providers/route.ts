import { vaultProxy } from "../_shared"

export const runtime = "nodejs"

/** Providers the vault knows how to talk to, and whether an operator key exists for each. */
export async function GET(req: Request) {
  return vaultProxy(req, "/vault/providers", { method: "GET" })
}
