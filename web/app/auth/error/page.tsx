"use client"

import { Suspense, useState } from "react"
import Link from "next/link"
import { useSearchParams } from "next/navigation"
import { HangulSigil } from "@/components/HangulSigil"
import { AppHeader } from "@/components/hangul/AppHeader"
import { SignInModal, type AuthMode } from "@/components/hangul/SignInModal"

/**
 * Where Auth.js sends the browser when sign-in fails (`pages.error` in
 * auth.config.ts). The `error` query param is one of Auth.js's error codes;
 * each gets plain-language copy and a sensible next step instead of the
 * default "Configuration" wall.
 */
const COPY: Record<string, { title: string; body: string }> = {
  OAuthAccountNotLinked: {
    title: "That email is already registered",
    body: "An account with this email already exists but was created a different way. Sign in with the method you used before, or request an email sign-in link — either way it is the same account.",
  },
  AccessDenied: {
    title: "We couldn't verify that account",
    body: "The email on that account isn't verified with its provider, so we can't use it to sign you in. Verify the email with your provider, or continue with the email link.",
  },
  Verification: {
    title: "That sign-in link has expired",
    body: "Magic links only work once and for a short time. Request a new one and open it on this device.",
  },
  Configuration: {
    title: "Sign-in isn't available right now",
    body: "Something on our side isn't set up correctly. Please try again in a moment, or use a different sign-in method.",
  },
  Default: {
    title: "Something went wrong signing you in",
    body: "Please try again. If it keeps happening, use a different sign-in method.",
  },
}

function ErrorInner() {
  const code = useSearchParams().get("error") ?? "Default"
  const copy = COPY[code] ?? COPY.Default
  const [modal, setModal] = useState<{ open: boolean; mode: AuthMode }>({ open: false, mode: "signin" })

  return (
    <main style={{ minHeight: "100vh", display: "flex", flexDirection: "column" }}>
      <AppHeader
        onSignIn={() => setModal({ open: true, mode: "signin" })}
        onSignUp={() => setModal({ open: true, mode: "signup" })}
      />
      <div style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", padding: "0 20px 80px", textAlign: "center" }}>
        <HangulSigil size={44} />
        <p className="h-display" style={{ fontSize: 24, margin: "20px 0 8px" }}>{copy.title}</p>
        <p className="h-muted" style={{ fontSize: 14, maxWidth: 420, margin: "0 0 24px", lineHeight: 1.5 }}>{copy.body}</p>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", justifyContent: "center" }}>
          <button className="h-btn-solid" style={{ padding: "10px 18px", fontSize: 14 }} onClick={() => setModal({ open: true, mode: "signin" })}>
            Try signing in again
          </button>
          <Link href="/" className="h-btn-outline" style={{ padding: "10px 18px", fontSize: 14, textDecoration: "none" }}>
            Back to home
          </Link>
        </div>
        <p className="h-muted" style={{ fontSize: 11, marginTop: 28 }}>Error code: {code}</p>
      </div>
      <SignInModal open={modal.open} mode={modal.mode} onClose={() => setModal((m) => ({ ...m, open: false }))} callbackUrl="/" />
    </main>
  )
}

export default function AuthErrorPage() {
  return (
    <Suspense fallback={null}>
      <ErrorInner />
    </Suspense>
  )
}
