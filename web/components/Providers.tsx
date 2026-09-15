"use client"

import { SessionProvider } from "next-auth/react"
import type { Session } from "next-auth"
import { ThemeProvider } from "@/components/ThemeProvider"

/**
 * `session` is resolved on the server (app/layout.tsx) and handed in, so the
 * client knows who is signed in from the first render — no "loading" window
 * to race against, and no initial fetch that a flaky network could fail.
 * refetchWhenOffline=false keeps a later network blip from being reported
 * as "unauthenticated".
 */
export function Providers({ children, session }: { children: React.ReactNode; session: Session | null }) {
  return (
    <SessionProvider session={session} refetchWhenOffline={false} refetchOnWindowFocus={true}>
      <ThemeProvider>{children}</ThemeProvider>
    </SessionProvider>
  )
}
