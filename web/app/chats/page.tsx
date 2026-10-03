"use client"

import { useState } from "react"
import { useRouter } from "next/navigation"
import { useSession } from "next-auth/react"
import { AppHeader } from "@/components/hangul/AppHeader"
import { SignInModal, type AuthMode } from "@/components/hangul/SignInModal"
import { ChatsPanel } from "@/components/hangul/ChatsPanel"

/** Chats (the phone tab): every conversation, full width; a row opens it in /chat. */
export default function ChatsPage() {
  const router = useRouter()
  const { status } = useSession()
  const [signIn, setSignIn] = useState<{ open: boolean; mode: AuthMode }>({ open: false, mode: "signin" })
  const [dismissed, setDismissed] = useState(false)
  return (
    <main className="h-has-bottom-nav" style={{ minHeight: "100vh", display: "flex", flexDirection: "column" }}>
      <AppHeader onSignIn={() => setSignIn({ open: true, mode: "signin" })} onSignUp={() => setSignIn({ open: true, mode: "signup" })}>
        {status === "authenticated" && (
          <button className="h-btn-solid" onClick={() => router.push("/chat")} style={{ borderRadius: 999, gap: 6, padding: "4px 12px" }} aria-label="New chat">
            <i className="ti ti-plus" style={{ fontSize: 14 }} /> New chat
          </button>
        )}
      </AppHeader>
      <SignInModal open={signIn.open || (status === "unauthenticated" && !dismissed)} mode={signIn.mode}
        onClose={() => { setDismissed(true); setSignIn((s) => ({ ...s, open: false })) }} callbackUrl="/chats" reason="Sign in to see your chats." />
      <div style={{ flex: 1, display: "flex", padding: "0 8px 16px", minHeight: 0 }}>
        {status === "authenticated" && <ChatsPanel fullPage onOpen={(id) => router.push(`/chat?c=${id}`)} />}
      </div>
    </main>
  )
}
