import { SignJWT } from "jose"

/**
 * Short-lived token the BFF presents to FastAPI on the user's behalf. `sub`
 * is the NextAuth users.id; `jti` lets the backend revoke a single token
 * (harness.auth.revocation) without rotating the shared secret.
 */
export async function mintServiceToken(userId: string, role: string = "user") {
  const secret = new TextEncoder().encode(process.env.FASTAPI_JWT_SECRET!)
  return await new SignJWT({ role })
    .setProtectedHeader({ alg: "HS256" })
    .setSubject(userId)
    .setJti(crypto.randomUUID())
    .setIssuedAt()
    .setExpirationTime("5m")
    .sign(secret)
}
