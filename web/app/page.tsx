"use client"

import { useState } from "react"
import { useRouter } from "next/navigation"
import { useSession } from "next-auth/react"
import { useTheme } from "@/components/ThemeProvider"
import { HangulSigil } from "@/components/HangulSigil"
import { AppHeader } from "@/components/hangul/AppHeader"
import { SignInModal, type AuthMode } from "@/components/hangul/SignInModal"
import { AttachMenu, type Attachment } from "@/components/hangul/AttachMenu"
import { AttachmentChips } from "@/components/hangul/AttachmentChips"

const PROMPTS = ["Search my documents", "Check the web", "Draft a note"]

export default function Landing() {
  const { status } = useSession()
  const router = useRouter()
  const { theme } = useTheme()
  const [signIn, setSignIn] = useState<{ open: boolean; mode: AuthMode; reason?: string }>({ open: false, mode: "signin" })
  const [input, setInput] = useState("")

  // Documents added here are already indexed server-side for this user; their
  // names ride along to /chat so the chips carry over.
  const [attachments, setAttachments] = useState<Attachment[]>([])
  const [uploading, setUploading] = useState<string | null>(null)
  const [uploadError, setUploadError] = useState<string | null>(null)

  const askToSignIn = (reason?: string) => setSignIn({ open: true, mode: "signin", reason })
  const askToSignUp = () => setSignIn({ open: true, mode: "signup" })

  // Signed-in users go straight to chat with their question; everyone else
  // has to sign in first.
  const onSubmit = (text = input) => {
    const q = text.trim()
    if (!q) return
    if (status !== "authenticated") return askToSignIn("Sign in to ask the agent.")
    const params = new URLSearchParams({ q })
    for (const a of attachments) params.append("doc", a.name)
    router.push(`/chat?${params}`)
  }

  return (
    <main style={{ minHeight: "100vh", display: "flex", flexDirection: "column" }}>
      <AppHeader showWordmark={false} onSignIn={() => askToSignIn()} onSignUp={askToSignUp} />

      <div style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", padding: "0 20px 80px" }}>
        <div style={{ filter: theme === "dark" ? "drop-shadow(0 0 10px rgba(242,243,245,0.18))" : "none" }}>
          <HangulSigil size={52} />
        </div>
        <p className="h-display" style={{ fontSize: 25, margin: "22px 0 26px" }}>What should we evaluate?</p>

        <div style={{ width: "100%", maxWidth: 460 }}>
          <AttachmentChips attachments={attachments} uploading={uploading} error={uploadError} style={{ marginBottom: 8 }} />
          <div className="h-surface" style={{ padding: "10px 12px 10px 10px", display: "flex", alignItems: "center", gap: 10 }}>
            <AttachMenu
              onUploaded={(a) => setAttachments((list) => [...list, a])}
              onUploadingChange={setUploading}
              onError={setUploadError}
              onRequireSignIn={askToSignIn}
              placement="below"
            />
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") onSubmit() }}
              placeholder={attachments.length ? "Ask about your document…" : "Ask anything…"}
              style={{ flex: 1, background: "none", border: "none", outline: "none", fontSize: 14, color: "var(--fg)" }}
            />
            <button className="h-icon-solid" onClick={() => onSubmit()} aria-label="Send">
              <i className="ti ti-arrow-up" style={{ fontSize: 16 }} />
            </button>
          </div>
        </div>

        <div style={{ display: "flex", gap: 8, marginTop: 16, flexWrap: "wrap", justifyContent: "center" }}>
          {PROMPTS.map((p) => (
            <button key={p} className="h-chip" onClick={() => onSubmit(p)}>{p}</button>
          ))}
        </div>
      </div>

      <SignInModal
        open={signIn.open}
        onClose={() => setSignIn((s) => ({ ...s, open: false }))}
        mode={signIn.mode}
        reason={signIn.reason}
        callbackUrl="/"
      />
    </main>
  )
}
