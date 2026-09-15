import Google from "next-auth/providers/google"
import { customFetch, type NextAuthConfig } from "next-auth"
import { resilientFetch } from "@/lib/resilientFetch"

export default {
  providers: [
    Google({
      clientId: process.env.AUTH_GOOGLE_ID,
      clientSecret: process.env.AUTH_GOOGLE_SECRET,
      // Retry transient connect failures on the server-side token exchange.
      [customFetch]: resilientFetch,
      // One person, one account. If a user already exists with this email
      // (e.g. they first signed in with a magic link) and now uses Google,
      // attach the Google identity to that user instead of failing with
      // OAuthAccountNotLinked. This is only safe because the signIn callback
      // below refuses Google profiles whose email Google has not verified.
      allowDangerousEmailAccountLinking: true,
    }),
  ],
  pages: {
    // Auth.js's default error page is unstyled and reads like a crash.
    // Ours explains the situation and offers a way forward.
    error: "/auth/error",
  },
  callbacks: {
    // Gate for the account linking above: Google asserts `email_verified` in
    // the OIDC profile. An unverified address must not be allowed to claim an
    // existing account, so those sign-ins are denied outright.
    signIn({ account, profile }) {
      if (account?.provider === "google") return profile?.email_verified === true
      return true
    },
    // With the JWT strategy the token's `sub` is users.id from the adapter, but
    // the default session only carries name/email/image. The BFF needs the id
    // because FastAPI keys memory, ledger and episodes on the integer users.id.
    session({ session, token }) {
      if (token.sub) session.user.id = token.sub
      return session
    },
  },
} satisfies NextAuthConfig
