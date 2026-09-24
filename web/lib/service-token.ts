import { SignJWT } from "jose"

/** Identity claims the admin routes forward so the backend can apply its allowlist. */
export type ServiceIdentity = { email: string; authProvider: string; authAt: number }

/**
 * Short-lived token the BFF presents to FastAPI on the user's behalf. `sub`
 * is the NextAuth users.id; `jti` lets the backend revoke a single token
 * (harness.auth.revocation) without rotating the shared secret.
 *
 * `identity` is only attached by the admin routes: the backend's
 * require_admin checks the email against its own allowlist, that the
 * sign-in came from Google, and that it is recent enough.
 */
export async function mintServiceToken(userId: string, role: string = "user", identity?: ServiceIdentity) {
  const secret = new TextEncoder().encode(process.env.FASTAPI_JWT_SECRET!)
  const claims: Record<string, unknown> = { role }
  if (identity) {
    claims.email = identity.email
    claims.auth_provider = identity.authProvider
    claims.auth_at = Math.floor(identity.authAt / 1000)
  }
  return await new SignJWT(claims)
    .setProtectedHeader({ alg: "HS256" })
    .setSubject(userId)
    .setJti(crypto.randomUUID())
    .setIssuedAt()
    .setExpirationTime("5m")
    .sign(secret)
}
