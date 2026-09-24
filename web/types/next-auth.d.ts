import type { DefaultSession } from "next-auth"

declare module "next-auth" {
  interface Session {
    user: DefaultSession["user"] & {
      id?: string
      /** Which Auth.js provider produced this session ("google" | "resend"). */
      provider?: string
      /** When the user last actually signed in (ms since epoch), not when the cookie was refreshed. */
      authAt?: number
    }
  }
}

declare module "next-auth/jwt" {
  interface JWT {
    provider?: string
    authAt?: number
  }
}
