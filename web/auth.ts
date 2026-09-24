import NextAuth from "next-auth"
import Resend from "next-auth/providers/resend"
import PostgresAdapter from "@auth/pg-adapter"
import { Pool } from "pg"
import authConfig from "@/auth.config"

const pool = new Pool({ connectionString: process.env.AUTH_PG_URL })

export const { handlers, auth, signIn, signOut } = NextAuth({
  adapter: PostgresAdapter(pool),
  session: { strategy: "jwt" },
  ...authConfig,
  providers: [...authConfig.providers, Resend({ from: process.env.AUTH_EMAIL_FROM })],
  callbacks: {
    ...authConfig.callbacks,
    // Record *how* and *when* the person signed in. `account` is only present
    // on the sign-in request itself, so these survive cookie refreshes
    // unchanged -- which is what lets the admin console demand a recent,
    // Google-backed sign-in rather than any old session.
    async jwt({ token, account }) {
      if (account) {
        token.provider = account.provider
        token.authAt = Date.now()
        // Connecting Google Workspace re-runs the Google sign-in with extra
        // scopes and offline access. The adapter only writes the accounts row
        // on first link, so the new refresh token + scopes are stored here;
        // the backend refreshes access tokens from them for the MCP bundle.
        if (account.provider === "google" && account.refresh_token) {
          try {
            await pool.query(
              `update accounts set refresh_token = $1, access_token = $2, scope = $3, expires_at = $4
               where provider = 'google' and "providerAccountId" = $5`,
              [account.refresh_token, account.access_token ?? null, account.scope ?? null,
               account.expires_at ?? null, account.providerAccountId],
            )
          } catch (e) {
            console.error("could not store Google tokens", (e as Error).message)
          }
        }
      }
      return token
    },
    session({ session, token }) {
      if (token.sub) session.user.id = token.sub
      session.user.provider = token.provider
      session.user.authAt = token.authAt
      return session
    },
  },
})
