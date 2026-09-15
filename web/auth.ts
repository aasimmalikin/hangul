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
})
