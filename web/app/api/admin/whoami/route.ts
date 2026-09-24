import { adminProxy } from "../_shared"

export const runtime = "nodejs"

/**
 * The page's first call after Google sign-in. 200 = this Google account is on
 * the backend's allowlist; 401 reauth_required = sign in (again) with Google;
 * 403 = signed in fine, just not an admin.
 */
export async function GET(req: Request) {
  return adminProxy(req, "/admin/whoami", { method: "GET" })
}
