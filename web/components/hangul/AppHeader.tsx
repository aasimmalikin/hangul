"use client"

import { useSession } from "next-auth/react"
import { Wordmark } from "@/components/Wordmark"
import { ProfileMenu } from "@/components/hangul/ProfileMenu"
import { ThemeMenu } from "@/components/hangul/ThemeMenu"

/**
 * The top bar every page shares: wordmark on the left, and on the right
 * either the signed-in user's avatar menu or Sign in / Sign up, then the
 * theme gear. `wordmarkHref={null}` renders the mark without a link, for the
 * page it would link to (the landing page).
 *
 * `onSignIn` / `onSignUp` open the page's SignInModal in the matching mode;
 * pages own the modal so they can word the reason ("sign in to upload", …).
 * `onSignUp` falls back to `onSignIn` when a page does not distinguish.
 */
export function AppHeader({
  showWordmark = true,
  wordmarkHref = "/",
  onSignIn,
  onSignUp,
  children,
}: {
  showWordmark?: boolean
  wordmarkHref?: string | null
  onSignIn: () => void
  onSignUp?: () => void
  children?: React.ReactNode
}) {
  const { status } = useSession()

  return (
    <header
      style={{
        display: "flex", alignItems: "center", gap: 8,
        padding: "14px 18px", flexShrink: 0,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 12, flex: 1, minWidth: 0 }}>
        {showWordmark && <Wordmark href={wordmarkHref} />}
        {children}
      </div>

      {status === "loading" ? (
        <span style={{ width: 32, height: 32 }} />
      ) : status === "authenticated" ? (
        <ProfileMenu />
      ) : (
        <>
          <button className="h-btn-ghost" onClick={onSignIn}>Sign in</button>
          <button className="h-btn-solid" onClick={onSignUp ?? onSignIn}>Sign up</button>
        </>
      )}
      <ThemeMenu />
    </header>
  )
}
