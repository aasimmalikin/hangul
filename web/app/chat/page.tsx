"use client"

import { Suspense, useCallback, useEffect, useRef, useState } from "react"
import { useRouter, useSearchParams } from "next/navigation"
import { useSession } from "next-auth/react"
import { useChat } from "@ai-sdk/react"
import type { UIMessage } from "ai"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import { Conversation, ConversationContent } from "@/components/ai-elements/conversation"
import { Message, MessageContent } from "@/components/ai-elements/message"
import { ToolRow, type ToolActivity } from "@/components/agent-activity"
import { HangulSigil } from "@/components/HangulSigil"
import { AppHeader } from "@/components/hangul/AppHeader"
import { SignInModal, type AuthMode } from "@/components/hangul/SignInModal"
import { AttachMenu, type Attachment } from "@/components/hangul/AttachMenu"
import { AttachmentChips } from "@/components/hangul/AttachmentChips"
import { StatusBanner } from "@/components/hangul/StatusBanner"
import { useConnectivity } from "@/components/hangul/useConnectivity"
import { parseApiFailure, failureFromResponse, type ApiFailure } from "@/lib/apiError"

type Approval = { runId: string; tool: string; arguments: Record<string, unknown> }
type ChoiceOption = { label: string; description: string }
type Choice = { runId: string; question: string; options: ChoiceOption[] }

type Part = {
  type: string
  text?: string
  id?: string
  data?: unknown
}

/**
 * What survives a refresh: the messages, answered approvals, attached docs.
 * Kept in sessionStorage, so it is scoped to *this tab*: a new tab is a new
 * conversation, and two tabs never mix their threads. Refresh, back and
 * forward within the tab restore it.
 */
type SavedThread = {
  messages: UIMessage[]
  resolved: Record<string, string>
  attachments: Attachment[]
  docsOnly?: boolean
  savedAt?: number
}
const STORAGE_PREFIX = "hangul:chat:"
const MAX_QUESTION_CHARS = 8_000

function loadThread(key: string): SavedThread | null {
  try {
    // One-time cleanup of the older shared-across-tabs copy.
    localStorage.removeItem(key)
    const raw = sessionStorage.getItem(key)
    if (!raw) return null
    const t = JSON.parse(raw) as Partial<SavedThread>
    if (!Array.isArray(t.messages)) return null
    return { messages: t.messages, resolved: t.resolved ?? {}, attachments: t.attachments ?? [], docsOnly: t.docsOnly ?? false, savedAt: t.savedAt }
  } catch {
    return null
  }
}
function saveThread(key: string, t: SavedThread) {
  try { sessionStorage.setItem(key, JSON.stringify({ ...t, savedAt: Date.now() })) } catch { /* quota / private mode */ }
}
function clearThread(key: string) {
  try { sessionStorage.removeItem(key) } catch { /* ignore */ }
}

function LinkRenderer(props: { href?: string; children?: React.ReactNode }) {
  return (
    <a href={props.href} target="_blank" rel="noopener noreferrer">
      {props.children}
    </a>
  )
}

function AnswerText({ text }: { text: string }) {
  return (
    <div className="h-prose">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={{ a: LinkRenderer }}>
        {text}
      </ReactMarkdown>
    </div>
  )
}

function Thinking() {
  return (
    <div className="flex items-center gap-2 py-2 text-sm" data-testid="thinking" style={{ color: "var(--muted)" }}>
      <span className="inline-flex gap-1">
        <span className="h-1.5 w-1.5 animate-pulse rounded-full" style={{ background: "var(--muted)" }} />
        <span className="h-1.5 w-1.5 animate-pulse rounded-full [animation-delay:150ms]" style={{ background: "var(--muted)" }} />
        <span className="h-1.5 w-1.5 animate-pulse rounded-full [animation-delay:300ms]" style={{ background: "var(--muted)" }} />
      </span>
      <span>Thinking…</span>
    </div>
  )
}

/** A card the agent puts in the thread when it needs the user — same surface as everything else. */
function Card({ tone = "neutral", children, testId }: { tone?: "neutral" | "warn" | "error"; children: React.ReactNode; testId?: string }) {
  const border = tone === "warn" ? "var(--warn)" : tone === "error" ? "var(--err)" : "var(--surface-border)"
  return (
    <div
      className="rounded-xl p-3"
      data-testid={testId}
      style={{ background: tone === "warn" ? "var(--warn-bg)" : "var(--surface)", border: `0.5px solid ${border}` }}
    >
      {children}
    </div>
  )
}

function ChatInner() {
  const { data: session, status: authStatus, update: refreshSession } = useSession()
  const router = useRouter()
  const connectivity = useConnectivity()

  // Sign-in gate. Sending a message and uploading a document both need a
  // session; the modal's copy says which one prompted it.
  const [signIn, setSignIn] = useState<{ open: boolean; mode: AuthMode; reason?: string }>({ open: false, mode: "signin" })
  const requireAuth = (reason: string) => {
    if (authStatus === "authenticated") return true
    if (authStatus === "loading") return false // caller queues; see pendingText
    if (!connectivity.online) {
      // Can't verify anything offline; don't tell the user they are signed out.
      setNotice({ code: "network", detail: "You're offline. Try again once you're connected." })
      return false
    }
    setSignIn({ open: true, mode: "signin", reason })
    return false
  }

  // A failure that isn't tied to a particular message (rate limit, backend
  // down, session expired). Rendered once, under the thread.
  const [notice, setNotice] = useState<ApiFailure | null>(null)
  const handleFailure = useCallback((f: ApiFailure) => {
    if (f.code === "unauthorized") {
      // The session cookie expired (or was revoked) mid-conversation.
      setSignIn({ open: true, mode: "signin", reason: "Your session has expired. Sign in again to continue — your conversation is kept." })
      void refreshSession()
      return
    }
    if (f.code === "upstream_unreachable" || f.code === "upstream_timeout" || f.code === "upstream_error" || f.code === "network") {
      void connectivity.recheck()
    }
    setNotice(f)
  }, [connectivity, refreshSession])

  const { messages, setMessages, sendMessage, regenerate, stop, status, error, clearError } = useChat({
    onError: (e) => handleFailure(parseApiFailure(e)),
  })
  const [input, setInput] = useState("")
  const [resolved, setResolved] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState<string | null>(null)
  const [docsOnly, setDocsOnly] = useState(false)

  // A question handed over from the landing page (`/chat?q=`), plus any
  // documents attached there (`&doc=`, already indexed server-side). Signed-in
  // users get the question sent straight away; everyone else sees the sign-in
  // gate, and the callback URL brings them back here with the params intact.
  const searchParams = useSearchParams()
  const q = searchParams.get("q")
  const [attachments, setAttachments] = useState<Attachment[]>(() =>
    searchParams.getAll("doc").map((name) => ({ name, chunks: 0 }))
  )
  const [uploading, setUploading] = useState<string | null>(null)
  const [uploadError, setUploadError] = useState<string | null>(null)

  // The thread lives in this tab's sessionStorage, keyed by user, so a refresh
  // brings it back instead of starting over while a new tab starts clean.
  // (The backend keeps checkpoints per run, not per conversation, so there
  // is nothing server-side to reload from.)
  const storageKey = session?.user?.id ? `${STORAGE_PREFIX}${session.user.id}` : null
  const restoredRef = useRef(false)
  useEffect(() => {
    if (!storageKey || restoredRef.current) return
    restoredRef.current = true
    const saved = loadThread(storageKey)
    if (!saved) return
    setMessages(saved.messages)
    // Restoring a saved thread is the one place state is synced from an
    // external store on mount; the lint rule is about cascading renders.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setResolved(saved.resolved)
    setAttachments((a) => (a.length ? a : saved.attachments))
    setDocsOnly(Boolean(saved.docsOnly))
  }, [storageKey, setMessages])

  const streaming = status === "submitted" || status === "streaming"
  // Save on every change, including mid-answer: if the user navigates away
  // while the agent is still talking, the question (and whatever streamed so
  // far) is there when they come back, flagged as cut short with a Retry.
  useEffect(() => {
    if (!storageKey || !restoredRef.current) return
    saveThread(storageKey, { messages, resolved, attachments, docsOnly })
  }, [storageKey, messages, resolved, attachments, docsOnly])

  // Send the handed-over question once, then drop it from the URL so a
  // refresh (or back/forward) does not send it again.
  const sentRef = useRef(false)
  useEffect(() => {
    if (!q || sentRef.current || authStatus !== "authenticated") return
    sentRef.current = true
    sendMessage({ text: q }, { body: { docsOnly } })
    router.replace("/chat")
  }, [q, sendMessage, authStatus, router, docsOnly])
  const [gateDismissed, setGateDismissed] = useState(false)
  const gateFromQuery = Boolean(q) && authStatus === "unauthenticated" && !gateDismissed

  // Typed and pressed Enter before the session cookie was checked: hold the
  // text and send it the moment we know who they are (or gate it if nobody).
  const [pendingText, setPendingText] = useState<string | null>(null)
  useEffect(() => {
    if (pendingText === null || authStatus === "loading") return
    const text = pendingText
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setPendingText(null)
    if (authStatus === "authenticated") {
      sendMessage({ text }, { body: { docsOnly } })
      setInput("")
    } else {
      setSignIn({ open: true, mode: "signin", reason: "Sign in to ask the agent." })
    }
  }, [pendingText, authStatus, sendMessage, docsOnly])

  const submit = () => {
    const text = input.trim()
    if (!text || streaming) return
    if (text.length > MAX_QUESTION_CHARS) {
      setNotice({ code: "bad_request", detail: `Questions are limited to ${MAX_QUESTION_CHARS} characters.` })
      return
    }
    if (authStatus === "loading") { setPendingText(text); return }
    if (!requireAuth("Sign in to ask the agent.")) return
    setNotice(null)
    clearError()
    sendMessage({ text }, { body: { docsOnly } })
    setInput("")
  }

  const retryLast = () => {
    setNotice(null)
    clearError()
    void regenerate({ body: { docsOnly } })
  }

  const newChat = () => {
    if (streaming) stop()
    setMessages([])
    setResolved({})
    setAttachments([])
    setUploadError(null)
    setNotice(null)
    clearError()
    if (storageKey) clearThread(storageKey)
  }

  const resume = async (runId: string, body: Record<string, unknown>) => {
    if (busy) return
    setBusy(runId)
    try {
      const res = await fetch("/api/approve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ approval_id: runId, ...body }),
        signal: AbortSignal.timeout(295_000),
      })
      if (!res.ok) {
        const f = await failureFromResponse(res)
        if (f.code === "unauthorized") { handleFailure(f); return }
        // A 404 means the action is no longer pending: already decided in
        // another tab, or the run expired. Say so instead of leaving buttons.
        setResolved((r) => ({ ...r, [runId]: res.status === 404 ? "This action was already handled." : f.detail }))
        return
      }
      const data = await res.json()
      setResolved((r) => ({ ...r, [runId]: data.answer || "Done." }))
    } catch {
      setResolved((r) => ({ ...r, [runId]: "Something went wrong resuming the run. Try again from a new message." }))
    } finally {
      setBusy(null)
    }
  }
  const decide = (runId: string, decision: "approve" | "reject") => resume(runId, { decision })
  const answer = (runId: string, choice: string) => resume(runId, { decision: "approve", choice })

  // Nothing has come back yet for the run in flight.
  const last = messages[messages.length - 1]
  const showThinking = streaming && (!last || last.role === "user" || last.parts.length === 0)

  // The last question never got any answer at all (tab navigated away before
  // the first token, request failed): offer a retry right there instead of a
  // dead end. A reply that *did* arrive is taken at face value — partial or
  // not, it is what the user saw, and only an explicit error says otherwise.
  const lastUserUnanswered = !streaming && last?.role === "user"
  const interrupted = Boolean(error) || lastUserUnanswered

  const renderPart = (part: Part, key: string) => {
    if (part.type === "text") {
      return part.text ? <AnswerText key={key} text={part.text} /> : null
    }

    if (part.type === "data-tool") {
      const activity = part.data as ToolActivity
      // ask_user has no result worth showing — the choice card below says it.
      if (activity.tool === "ask_user") return null
      return <ToolRow key={key} activity={activity} />
    }

    if (part.type === "data-run") {
      // Run bookkeeping (steps, cost, tools) travels with the message for
      // the record but is not shown — an invisible marker that the run ended.
      return <span key={key} data-testid="run-done" hidden />
    }

    if (part.type === "data-choice") {
      const choice = part.data as Choice
      if (resolved[choice.runId] !== undefined) {
        return <AnswerText key={key} text={resolved[choice.runId]} />
      }
      return (
        <Card key={key} testId="choice-card">
          <p className="mb-2 text-sm">{choice.question}</p>
          <div className="flex flex-col gap-2">
            {choice.options.map((opt) => (
              <button
                key={opt.label}
                onClick={() => answer(choice.runId, opt.label)}
                disabled={busy === choice.runId}
                className="h-btn-outline"
                style={{ justifyContent: "flex-start", flexDirection: "column", alignItems: "flex-start", gap: 2, padding: "8px 12px", lineHeight: 1.3 }}
              >
                <span style={{ fontWeight: 500 }}>{opt.label}</span>
                {opt.description ? <span className="h-muted" style={{ fontSize: 12 }}>{opt.description}</span> : null}
              </button>
            ))}
          </div>
        </Card>
      )
    }

    if (part.type === "data-approval") {
      const approval = part.data as Approval
      if (resolved[approval.runId] !== undefined) {
        return <AnswerText key={key} text={resolved[approval.runId]} />
      }
      return (
        <Card key={key} tone="warn" testId="approval-card">
          <p className="mb-2 text-sm">
            The assistant wants to run <code style={{ fontFamily: "var(--font-geist-mono)", fontSize: 12 }}>{approval.tool}</code>. Allow it?
          </p>
          <div className="flex gap-2">
            <button className="h-btn-solid" onClick={() => decide(approval.runId, "approve")} disabled={busy === approval.runId}>
              {busy === approval.runId ? "…" : "Approve"}
            </button>
            <button className="h-btn-outline" onClick={() => decide(approval.runId, "reject")} disabled={busy === approval.runId}>
              Reject
            </button>
          </div>
        </Card>
      )
    }

    return null
  }

  const canSend = !streaming && input.trim().length > 0 && connectivity.online

  return (
    <main style={{ height: "100vh", display: "flex", flexDirection: "column" }}>
      <AppHeader
        onSignIn={() => setSignIn({ open: true, mode: "signin" })}
        onSignUp={() => setSignIn({ open: true, mode: "signup" })}
      >
        {messages.length > 0 && (
          <button className="h-btn-ghost" onClick={newChat} title="Start a new conversation">
            <i className="ti ti-plus" style={{ fontSize: 14 }} />
            New chat
          </button>
        )}
      </AppHeader>
      <StatusBanner c={connectivity} />

      <Conversation className="flex-1">
        <ConversationContent className="mx-auto min-h-full w-full max-w-3xl px-5 py-6">
          {messages.length === 0 ? (
            <div className="flex flex-1 flex-col items-center justify-center gap-3 p-8 text-center">
              <HangulSigil size={40} />
              <p className="h-display" style={{ fontSize: 22, margin: "8px 0 0" }}>Ask anything</p>
              <p className="h-muted" style={{ fontSize: 13, maxWidth: 360 }}>
                Your documents, the web, and your connected tools. Use <b>+</b> to add a document and ask about it.
              </p>
            </div>
          ) : (
            messages.map((m) => (
              <Message from={m.role} key={m.id}>
                {/* Parts arrive in the order the agent produced them, so the
                    narration, the tool it ran, and the answer read as one
                    running commentary. */}
                <MessageContent className="group-[.is-user]:rounded-2xl">
                  {(m.parts as Part[]).map((p, i) => renderPart(p, `${m.id}-${i}`))}
                </MessageContent>
              </Message>
            ))
          )}
          {showThinking && <Thinking />}

          {(notice || (interrupted && messages.length > 0)) && (
            <Card tone="error" testId="notice-card">
              <p className="text-sm" style={{ margin: 0 }}>
                {notice?.detail ?? (error ? parseApiFailure(error).detail : "That question didn't get an answer.")}
              </p>
              {authStatus === "authenticated" && messages.some((m) => m.role === "user") && (
                <div className="flex gap-2" style={{ marginTop: 8 }}>
                  <button className="h-btn-solid" onClick={retryLast} disabled={streaming || !connectivity.online} data-testid="retry">
                    Retry
                  </button>
                  <button className="h-btn-ghost" onClick={() => { setNotice(null); clearError() }}>Dismiss</button>
                </div>
              )}
            </Card>
          )}
        </ConversationContent>
      </Conversation>

      {/* Composer — the same box as the landing page, with a + on the left for documents. */}
      <div style={{ padding: "8px 20px 20px", flexShrink: 0 }}>
        <div style={{ maxWidth: 720, margin: "0 auto" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 8, flexWrap: "wrap" }}>
            <AttachmentChips attachments={attachments} uploading={uploading} error={uploadError} />
            {/* Documents-only mode: the backend restricts the agent to search_docs and
                forbids answering from its own knowledge. */}
            <button
              type="button"
              className="h-chip"
              data-testid="docs-only"
              aria-pressed={docsOnly}
              onClick={() => setDocsOnly((v) => !v)}
              title="Answer only from your documents — no web, no general knowledge"
              style={docsOnly ? { background: "var(--solid-bg)", color: "var(--solid-fg)", borderColor: "var(--solid-bg)" } : undefined}
            >
              <i className="ti ti-book-2" style={{ fontSize: 12, marginRight: 5 }} />
              Documents only
            </button>
          </div>

          <form
            onSubmit={(e) => { e.preventDefault(); submit() }}
            className="h-surface"
            style={{ padding: "10px 12px 10px 10px", display: "flex", alignItems: "flex-end", gap: 10 }}
          >
            <AttachMenu
              onUploaded={(a) => setAttachments((list) => [...list, a])}
              onUploadingChange={setUploading}
              onError={(msg) => {
                setUploadError(msg)
              }}
              onRequireSignIn={(reason) => setSignIn({ open: true, mode: "signin", reason })}
            />
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit() }
              }}
              placeholder={attachments.length ? "Ask about your document…" : "Ask anything…"}
              rows={1}
              maxLength={MAX_QUESTION_CHARS}
              style={{
                flex: 1, resize: "none", background: "none", border: "none", outline: "none",
                fontSize: 14, color: "var(--fg)", lineHeight: "22px", padding: "5px 0",
                maxHeight: 160, overflowY: "auto", fontFamily: "inherit",
              }}
              onInput={(e) => {
                const el = e.currentTarget
                el.style.height = "auto"
                el.style.height = `${Math.min(el.scrollHeight, 160)}px`
              }}
            />
            {streaming ? (
              <button type="button" className="h-icon-solid" style={{ flexShrink: 0 }} onClick={() => stop()} aria-label="Stop" title="Stop generating">
                <i className="ti ti-player-stop-filled" style={{ fontSize: 14 }} />
              </button>
            ) : (
              <button type="submit" className="h-icon-solid" style={{ flexShrink: 0 }} disabled={!canSend} aria-label="Send">
                <i className="ti ti-arrow-up" style={{ fontSize: 16 }} />
              </button>
            )}
          </form>
        </div>
      </div>

      <SignInModal
        open={signIn.open || gateFromQuery}
        onClose={() => { setSignIn((s) => ({ ...s, open: false })); setGateDismissed(true) }}
        mode={signIn.open ? signIn.mode : "signin"}
        reason={signIn.open ? signIn.reason : "Sign in to ask the agent."}
      />
    </main>
  )
}

export default function Chat() {
  // useSearchParams needs a Suspense boundary for the static shell.
  return (
    <Suspense fallback={null}>
      <ChatInner />
    </Suspense>
  )
}
