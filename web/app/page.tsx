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
import { ConnectorChips } from "@/components/hangul/ConnectorChips"
import { useConnectorSelection, useResearchMode } from "@/lib/connectors"
import { ChatsPanel } from "@/components/hangul/ChatsPanel"

const PROMPTS = ["Search my documents", "Check the web", "Draft a note"]
// How tall the composer grows before it scrolls: ~8 lines at 22px.
const MAX_COMPOSER_PX = 200

export default function Landing() {
  const { status } = useSession()
  const router = useRouter()
  const { theme } = useTheme()
  const [signIn, setSignIn] = useState<{ open: boolean; mode: AuthMode; reason?: string }>({ open: false, mode: "signin" })
  const [input, setInput] = useState("")

  // Documents added here are already indexed server-side for this user; their
  // names ride along to /chat so the chips carry over.
  const [attachments, setAttachments] = useState<Attachment[]>([])
  // Carried to /chat through this tab's sessionStorage, like the attachments go through the URL.
  const [connectors, setConnectors] = useConnectorSelection()
  const [research, setResearch] = useResearchMode()
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
    <main style={{ height: "100vh", display: "flex", flexDirection: "column" }}>
      {/* Same wordmark as every other page; plain (not a link) because this is home. */}
      <AppHeader wordmarkHref={null} onSignIn={() => askToSignIn()} onSignUp={askToSignUp} />

      <div style={{ flex: 1, display: "flex", minHeight: 0 }}>
      {/* Same rail as /chat: the user's conversations, visible right after sign-in. */}
      {status === "authenticated" && <ChatsPanel onUnauthorized={() => askToSignIn("Your session has expired. Sign in again.")} onOpen={(id) => router.push(`/chat?c=${id}`)} />}
      <div style={{ flex: 1, minWidth: 0, overflowY: "auto", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", padding: "0 20px 80px" }}>
        <div style={{ filter: theme === "dark" ? "drop-shadow(0 0 10px rgba(242,243,245,0.18))" : "none" }}>
          <HangulSigil size={52} />
        </div>
        <p className="h-display" style={{ fontSize: 25, margin: "22px 0 26px" }}>What should we evaluate?</p>

        {/* Wide enough to write a real question in (was 460); still centred and clear of the rail. */}
        <div style={{ width: "100%", maxWidth: 640 }} data-testid="landing-composer-box">
          <AttachmentChips attachments={attachments} uploading={uploading} error={uploadError} style={{ marginBottom: 8 }} />
          <div className="h-surface" style={{ padding: "10px 12px 10px 10px", display: "flex", alignItems: "flex-end", gap: 10 }}>
            <AttachMenu
              onUploaded={(a) => setAttachments((list) => [...list, a])}
              onUploadingChange={setUploading}
              onError={setUploadError}
              onRequireSignIn={askToSignIn}
              placement="below"
              connectors={connectors}
              onConnectorsChange={setConnectors}
            />
            {/* Same composer as /chat: wraps and grows a line at a time (up to
                MAX_COMPOSER_PX, then scrolls). Enter sends, Shift+Enter is a newline. */}
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); onSubmit() }
              }}
              placeholder={attachments.length ? "Ask about your document…" : "Ask anything…"}
              rows={1}
              data-testid="landing-composer"
              style={{
                flex: 1, resize: "none", background: "none", border: "none", outline: "none",
                fontSize: 14, color: "var(--fg)", lineHeight: "22px", padding: "5px 0",
                maxHeight: MAX_COMPOSER_PX, overflowY: "auto", overflowX: "hidden", fontFamily: "inherit",
              }}
              onInput={(e) => {
                const el = e.currentTarget
                el.style.height = "auto"
                el.style.height = `${Math.min(el.scrollHeight, MAX_COMPOSER_PX)}px`
              }}
            />
            <button className="h-icon-solid" onClick={() => onSubmit()} aria-label="Send" style={{ flexShrink: 0 }}>
              <i className="ti ti-arrow-up" style={{ fontSize: 16 }} />
            </button>
          </div>
        </div>

        <div style={{ display: "flex", gap: 8, marginTop: 16, flexWrap: "wrap", justifyContent: "center" }}>
          <button
            type="button"
            className="h-chip"
            data-testid="research-mode"
            aria-pressed={research}
            onClick={() => setResearch(!research)}
            title="Deep research: plan, several searches (documents, web, arXiv), numbered citations and a sources list"
            style={research ? { background: "var(--solid-bg)", color: "var(--solid-fg)", borderColor: "var(--solid-bg)" } : undefined}
          >
            <i className="ti ti-telescope" style={{ fontSize: 12, marginRight: 5 }} />
            Deep research
          </button>
          <ConnectorChips keys={connectors} onChange={setConnectors} />
          {PROMPTS.map((p) => (
            <button key={p} className="h-chip" onClick={() => onSubmit(p)}>{p}</button>
          ))}
        </div>
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
