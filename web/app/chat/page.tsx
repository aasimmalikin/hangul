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
import { ActivityGroup, toolName, type ActivityItem, type ToolActivity } from "@/components/agent-activity"
import { HangulSigil } from "@/components/HangulSigil"
import { AppHeader } from "@/components/hangul/AppHeader"
import { SignInModal, type AuthMode } from "@/components/hangul/SignInModal"
import { AttachMenu, type Attachment } from "@/components/hangul/AttachMenu"
import { AttachmentChips } from "@/components/hangul/AttachmentChips"
import { StatusBanner } from "@/components/hangul/StatusBanner"
import { ChatsPanel } from "@/components/hangul/ChatsPanel"
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
  /** Conversation id: what the "Chats" rail entry is keyed by (episodes.thread_id). */
  threadId?: string
}
const STORAGE_PREFIX = "hangul:chat:"
const MAX_QUESTION_CHARS = 8_000
// How tall the composer grows before it scrolls: ~8 lines at 22px.
const MAX_COMPOSER_PX = 200
const newThreadId = () => crypto.randomUUID()

/**
 * What the "Chats" rail stores about a conversation: its title (the first
 * question) and a compact transcript the backend embeds for
 * `recall_episodes`. Built here from the UI messages — no model call.
 */
function summariseThread(messages: UIMessage[]): { title: string; summary: string } | null {
  const lines: string[] = []
  let title = ""
  for (const m of messages) {
    const text = (m.parts as Part[]).filter((p) => p.type === "text" && p.text).map((p) => p.text!.trim()).join(" ").trim()
    if (!text) continue
    if (m.role === "user") {
      if (!title) title = text
      lines.push(`Q: ${text.slice(0, 300)}`)
    } else if (m.role === "assistant") {
      lines.push(`A: ${text.slice(0, 300)}`)
    }
  }
  if (!title) return null
  return { title: title.slice(0, 200), summary: lines.join("\n").slice(0, 2048) }
}

function loadThread(key: string): SavedThread | null {
  try {
    // One-time cleanup of the older shared-across-tabs copy.
    localStorage.removeItem(key)
    const raw = sessionStorage.getItem(key)
    if (!raw) return null
    const t = JSON.parse(raw) as Partial<SavedThread>
    if (!Array.isArray(t.messages)) return null
    return { messages: t.messages, resolved: t.resolved ?? {}, attachments: t.attachments ?? [], docsOnly: t.docsOnly ?? false, savedAt: t.savedAt, threadId: t.threadId }
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

/** Completed runs in a thread — every run ends with a hidden data-run part. */
function countRuns(messages: UIMessage[]) {
  return messages.reduce((n, m) => n + (m.parts as Part[]).filter((p) => p.type === "data-run").length, 0)
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

/**
 * Exactly what the agent is asking permission to do, laid out so the user can
 * read it before deciding: the file and its full content for writes, the
 * edits for edits, a plain key/value list for anything else.
 */
function ActionDetails({ tool, args }: { tool: string; args: Record<string, unknown> }) {
  const path = typeof args.path === "string" ? args.path : null
  const content = typeof args.content === "string" ? args.content : null
  const edits = Array.isArray(args.edits) ? (args.edits as Record<string, unknown>[]) : null
  const rest = Object.entries(args).filter(([k]) => !["path", "content", "edits"].includes(k))
  const mono = { fontFamily: "var(--font-geist-mono)", fontSize: 12 } as const

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {path && (
        <div style={{ fontSize: 13 }}>
          <span className="h-muted">File </span>
          <span style={{ ...mono, fontWeight: 500 }}>{path.split("/").slice(-1)[0]}</span>
          <div className="h-muted" style={{ ...mono, fontSize: 11, wordBreak: "break-all" }}>{path}</div>
        </div>
      )}
      {content !== null && (
        <div>
          <div className="h-muted" style={{ fontSize: 12, marginBottom: 4 }}>
            Content to write · {content.length.toLocaleString()} characters
          </div>
          <pre
            data-testid="approval-content"
            className="max-h-72 overflow-auto whitespace-pre-wrap rounded-lg p-3"
            style={{ ...mono, background: "var(--bubble)", border: "0.5px solid var(--surface-border)", color: "var(--fg)", margin: 0 }}
          >
            {content}
          </pre>
        </div>
      )}
      {edits && (
        <div>
          <div className="h-muted" style={{ fontSize: 12, marginBottom: 4 }}>{edits.length} {edits.length === 1 ? "edit" : "edits"}</div>
          {edits.map((e, i) => (
            <pre key={i} className="mb-1 max-h-40 overflow-auto whitespace-pre-wrap rounded-lg p-3" style={{ ...mono, background: "var(--bubble)", border: "0.5px solid var(--surface-border)", color: "var(--fg)", margin: "0 0 6px" }}>
              <span style={{ color: "var(--err)" }}>- {String(e.oldText ?? "")}</span>{"\n"}
              <span style={{ color: "var(--ok)" }}>+ {String(e.newText ?? "")}</span>
            </pre>
          ))}
        </div>
      )}
      {rest.length > 0 && (
        <dl style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: "2px 10px", fontSize: 12, margin: 0 }}>
          {rest.map(([k, v]) => (
            <div key={k} style={{ display: "contents" }}>
              <dt className="h-muted">{k}</dt>
              <dd style={{ ...mono, margin: 0, wordBreak: "break-word" }}>{typeof v === "string" ? v : JSON.stringify(v)}</dd>
            </div>
          ))}
        </dl>
      )}
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
  const [threadId, setThreadId] = useState<string>(newThreadId)

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
  // Arriving with `?q=` is a hand-off from the landing page ("Draft a note",
  // "Check the web", a typed question): that is a *new* conversation, so the
  // tab's previous thread is dropped instead of the question being appended
  // to it. Captured once at mount — the URL loses `q` right after sending,
  // and a plain refresh (no `q`) must still restore. Nothing server-side is
  // lost: every run stays checkpointed and `remember` facts persist.
  const handoffRef = useRef(Boolean(q))
  // Runs already saved to the Chats rail (so a restored thread is not re-saved).
  const savedRunsRef = useRef(0)
  useEffect(() => {
    if (!storageKey || restoredRef.current) return
    restoredRef.current = true
    if (handoffRef.current) { clearThread(storageKey); return }
    const saved = loadThread(storageKey)
    if (!saved) return
    setMessages(saved.messages)
    // Restoring a saved thread is the one place state is synced from an
    // external store on mount; the lint rule is about cascading renders.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setResolved(saved.resolved)
    setAttachments((a) => (a.length ? a : saved.attachments))
    setDocsOnly(Boolean(saved.docsOnly))
    if (saved.threadId) setThreadId(saved.threadId)
    savedRunsRef.current = countRuns(saved.messages)
  }, [storageKey, setMessages])

  const streaming = status === "submitted" || status === "streaming"
  // Save on every change, including mid-answer: if the user navigates away
  // while the agent is still talking, the question (and whatever streamed so
  // far) is there when they come back, flagged as cut short with a Retry.
  useEffect(() => {
    if (!storageKey || !restoredRef.current) return
    saveThread(storageKey, { messages, resolved, attachments, docsOnly, threadId })
  }, [storageKey, messages, resolved, attachments, docsOnly, threadId])

  // Every completed run saves the conversation to the Chats rail (upsert by
  // threadId), so it is already listed when the user goes back to the
  // landing page. `chatsVersion` bumps after a save so the rail on this
  // page refetches.
  const runsDone = countRuns(messages)
  const [chatsVersion, setChatsVersion] = useState(0)
  useEffect(() => {
    if (runsDone === 0 || runsDone <= savedRunsRef.current) return
    savedRunsRef.current = runsDone
    const s = summariseThread(messages)
    if (!s) return
    let alive = true
    fetch("/api/chats", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ thread_id: threadId, ...s }),
      signal: AbortSignal.timeout(20_000),
    })
      .then((r) => { if (alive && r.ok) setChatsVersion((v) => v + 1) })
      .catch(() => { /* the rail just won't show this chat until the next run */ })
    return () => { alive = false }
  }, [runsDone, messages, threadId])

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
    setThreadId(newThreadId())
    savedRunsRef.current = 0
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
  // An assistant turn with nothing readable in it (only status/tool rows —
  // e.g. stopped before the first token) counts as no answer too.
  const lastAssistantEmpty = !streaming && last?.role === "assistant" &&
    !(last.parts as Part[]).some((p) => (p.type === "text" && p.text?.trim()) || p.type === "data-approval" || p.type === "data-choice")
  const interrupted = Boolean(error) || lastUserUnanswered || lastAssistantEmpty

  /**
   * Parts arrive in the order the agent produced them. Text is rendered as
   * is; every unbroken run of activity (tool calls, "thinking" gaps) between
   * texts is folded into one ActivityGroup, so the thread reads as
   * narration → one compact block of work → answer, instead of a list that
   * grows a line per step. The block is live only while it is the last
   * thing in the last message of a run that is still streaming.
   */
  const renderParts = (parts: Part[], msgId: string, isLast: boolean) => {
    const out: React.ReactNode[] = []
    let group: ActivityItem[] = []
    const flush = (live: boolean) => {
      if (group.length === 0) return
      out.push(<ActivityGroup key={`${msgId}-g${out.length}`} items={group} live={live} />)
      group = []
    }
    parts.forEach((part, i) => {
      const key = `${msgId}-${i}`
      if (part.type === "data-tool") {
        const activity = part.data as ToolActivity
        // ask_user has no result worth showing — the choice card below says it.
        if (activity.tool !== "ask_user") group.push({ kind: "tool", key, activity })
        return
      }
      if (part.type === "data-status") {
        // The model is between outputs (deciding, or generating a tool call
        // it has not named yet). Only meaningful while the run is live.
        const st = part.data as { phase: "thinking" | "idle"; step?: number }
        if (st.phase === "thinking" && streaming && isLast) group.push({ kind: "thinking", key, step: st.step })
        return
      }
      if (part.type === "data-run") {
        // Run bookkeeping (steps, cost, tools) travels with the message for
        // the record but is not shown — an invisible marker that the run ended.
        flush(false)
        out.push(<span key={key} data-testid="run-done" hidden />)
        return
      }
      flush(false)
      out.push(renderPart(part, key))
    })
    // Whatever is still open at the end is the current work, if the run is live.
    flush(streaming && isLast)
    return out
  }

  const renderPart = (part: Part, key: string) => {
    if (part.type === "text") {
      return part.text ? <AnswerText key={key} text={part.text} /> : null
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
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
            <i className="ti ti-hand-stop" style={{ color: "var(--warn)", fontSize: 16 }} />
            <span className="h-display" style={{ fontSize: 16 }}>Approve this action?</span>
            <span className="h-muted" style={{ fontSize: 12, marginLeft: "auto", fontFamily: "var(--font-geist-mono)" }}>{toolName(approval.tool)}</span>
          </div>
          <ActionDetails tool={approval.tool} args={approval.arguments ?? {}} />
          <p className="h-muted" style={{ fontSize: 12, margin: "10px 0 8px" }}>
            Nothing has been changed yet. The agent will only continue once you decide.
          </p>
          <div className="flex gap-2">
            <button className="h-btn-solid" onClick={() => decide(approval.runId, "approve")} disabled={busy === approval.runId}>
              <i className="ti ti-check" style={{ fontSize: 14 }} />
              {busy === approval.runId ? "Working…" : "Approve"}
            </button>
            <button className="h-btn-outline" onClick={() => decide(approval.runId, "reject")} disabled={busy === approval.runId}>
              <i className="ti ti-x" style={{ fontSize: 14 }} />
              Reject
            </button>
          </div>
        </Card>
      )
    }

    return null
  }

  const canSend = !streaming && input.trim().length > 0 && connectivity.online

  const onChatsUnauthorized = useCallback(() => handleFailure({ code: "unauthorized", detail: "Sign in to continue." }), [handleFailure])

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

      <div style={{ flex: 1, display: "flex", minHeight: 0 }}>
      {authStatus === "authenticated" && <ChatsPanel refreshKey={chatsVersion} onUnauthorized={onChatsUnauthorized} />}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
      <Conversation className="flex-1">
        <ConversationContent className="mx-auto min-h-full w-full max-w-3xl px-5 py-6" data-testid="thread">
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
                  {m.role === "assistant"
                    ? renderParts(m.parts as Part[], m.id, m === last)
                    : (m.parts as Part[]).map((p, i) => renderPart(p, `${m.id}-${i}`))}
                </MessageContent>
              </Message>
            ))
          )}
          {showThinking && <ActivityGroup items={[{ kind: "thinking", key: "pre" }]} live />}

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
              data-testid="chat-composer"
              maxLength={MAX_QUESTION_CHARS}
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
            {streaming ? (
              <button type="button" className="h-icon-solid" style={{ flexShrink: 0 }} onClick={() => stop()} aria-label="Stop" title="Stop generating">
                <i className="ti ti-player-stop" style={{ fontSize: 15 }} />
              </button>
            ) : (
              <button type="submit" className="h-icon-solid" style={{ flexShrink: 0 }} disabled={!canSend} aria-label="Send">
                <i className="ti ti-arrow-up" style={{ fontSize: 16 }} />
              </button>
            )}
          </form>
        </div>
      </div>
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
