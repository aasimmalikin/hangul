"use client"

import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react"
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
import { ConnectorChips } from "@/components/hangul/ConnectorChips"
import { GmailCompose, GoogleCard, isGoogleUi } from "@/components/hangul/GoogleCards"
import { readConnectors, readResearchMode, writeConnectors, writeResearchMode } from "@/lib/connectors"
import { ModelPicker } from "@/components/hangul/ModelPicker"
import { StatusBanner } from "@/components/hangul/StatusBanner"
import { ChatsPanel } from "@/components/hangul/ChatsPanel"
import { useConnectivity } from "@/components/hangul/useConnectivity"
import { parseApiFailure, failureFromResponse, type ApiFailure } from "@/lib/apiError"

type Approval = { runId: string; tool: string; arguments: Record<string, unknown> }
type SecurityNotice = { layer: "input" | "tool_result" | "action" | "output"; severity: "low" | "medium" | "high"; source: string; action: string; reasons: string[]; step: number | null; answer?: string }
type ChoiceOption = { label: string; description: string }
type Choice = { runId: string; question: string; options: ChoiceOption[] }

type Part = {
  type: string
  text?: string
  id?: string
  data?: unknown
}

/**
 * What a tab caches about a conversation: the messages, answered approvals,
 * attached docs and the settings it was started with.
 *
 * The SERVER owns the transcript now (`conversation_messages`), so this is an
 * optimistic cache, not the record: it paints instantly on a refresh and is
 * then reconciled against `GET /api/conversations/<id>`. It is still keyed per
 * tab AND per conversation, so two tabs on different chats never mix, and one
 * tab can switch between chats without losing either.
 */
type SavedThread = {
  messages: UIMessage[]
  resolved: Record<string, string>
  attachments: Attachment[]
  docsOnly?: boolean
  connectors?: string[]
  mode?: "default" | "research"
  /** Model / reasoning effort chosen for this conversation; null = server default. */
  model?: string | null
  effort?: string | null
  savedAt?: number
  /** Server-side conversation id (conversations.id); null until the first run. */
  conversationId?: string | null
}
const STORAGE_PREFIX = "hangul:chat:"
/** Which conversation this tab is currently showing. */
const ACTIVE_PREFIX = "hangul:chat:active:"
const MAX_QUESTION_CHARS = 8_000
// How tall the composer grows before it scrolls: ~8 lines at 22px.
const MAX_COMPOSER_PX = 200

/** One message of a stored transcript, as GET /api/conversations/<id> sends it. */
type TranscriptMessage = {
  seq: number
  role: "user" | "assistant" | "tool"
  content: string
  tool_calls?: { id?: string; function?: { name?: string; arguments?: string } }[]
  tool_call_id?: string | null
  ui?: unknown
}

type ConversationDetail = {
  id: string
  title: string
  model?: string | null
  effort?: string | null
  connectors?: string[]
  mode?: string
  docs_only?: boolean
  messages?: TranscriptMessage[]
}

/**
 * Rebuild the chat UI from a stored transcript.
 *
 * The transcript is in OpenAI wire shape (assistant turns carrying tool_calls,
 * then one `tool` message per call); the UI wants one message per turn with
 * `data-tool` parts. So tool results are matched back to the call that asked
 * for them by `tool_call_id` and folded into that assistant message — the same
 * shape the live stream produces, so the renderer needs no special case.
 *
 * Each restored run gets its own hidden `data-run` marker — that is how the
 * page counts finished runs (and how the e2e tests spot the end of one). A run
 * ends at the last assistant message before the next user turn, so the count
 * matches what the live stream would have produced.
 */
function toUIMessages(rows: TranscriptMessage[]): UIMessage[] {
  const out: UIMessage[] = []
  // tool_call_id -> the part to fill in when its result arrives
  const awaiting = new Map<string, { activity: ToolActivity }>()

  const pushAssistant = (parts: Part[]) => {
    out.push({ id: `restored-a-${out.length}`, role: "assistant", parts } as unknown as UIMessage)
  }

  /** Close the run that the last assistant message belongs to. */
  const endRun = () => {
    const last = out[out.length - 1] as unknown as { role: string; parts: Part[] } | undefined
    if (last?.role === "assistant" && !last.parts.some((p) => p.type === "data-run")) {
      last.parts.push({ type: "data-run", data: { restored: true } })
    }
  }

  for (const row of rows) {
    if (row.role === "user") {
      // a new question means the previous run finished
      endRun()
      out.push({
        id: `restored-u-${out.length}`, role: "user",
        parts: [{ type: "text", text: row.content }],
      } as unknown as UIMessage)
      continue
    }

    if (row.role === "tool") {
      const slot = row.tool_call_id ? awaiting.get(row.tool_call_id) : undefined
      if (slot) {
        slot.activity.status = row.content.startsWith("Error") ? "error" : "done"
        slot.activity.preview = row.content
        if (row.ui) slot.activity.ui = row.ui as ToolActivity["ui"]
        if (row.tool_call_id) awaiting.delete(row.tool_call_id)
      }
      continue
    }

    // assistant
    const parts: Part[] = []
    if (row.content) parts.push({ type: "text", text: row.content })
    for (const tc of row.tool_calls ?? []) {
      let args: Record<string, unknown> = {}
      try { args = JSON.parse(tc.function?.arguments || "{}") } catch { /* keep {} */ }
      // Status starts as "done": a stored call already ran. A `tool` row later
      // in the transcript corrects it to "error" if it failed.
      const activity: ToolActivity = { tool: tc.function?.name ?? "tool", arguments: args, status: "done" }
      parts.push({ type: "data-tool", id: tc.id, data: activity })
      if (tc.id) awaiting.set(tc.id, { activity })
    }
    if (parts.length) pushAssistant(parts)
  }

  // The final run has no following user turn to close it.
  endRun()
  return out
}

/** This tab's cache slot for one conversation. "new" until the server names it. */
function slotKey(userId: string, conversationId: string | null): string {
  return `${STORAGE_PREFIX}${userId}:${conversationId ?? "new"}`
}

function readActive(userId: string): string | null {
  try { return sessionStorage.getItem(`${ACTIVE_PREFIX}${userId}`) } catch { return null }
}

function writeActive(userId: string, conversationId: string | null) {
  try {
    const k = `${ACTIVE_PREFIX}${userId}`
    if (conversationId) sessionStorage.setItem(k, conversationId)
    else sessionStorage.removeItem(k)
  } catch { /* quota / private mode */ }
}

function loadThread(key: string): SavedThread | null {
  try {
    // One-time cleanup of the older shared-across-tabs copy.
    localStorage.removeItem(key)
    const raw = sessionStorage.getItem(key)
    if (!raw) return null
    const t = JSON.parse(raw) as Partial<SavedThread>
    if (!Array.isArray(t.messages)) return null
    return {
      messages: t.messages, resolved: t.resolved ?? {}, attachments: t.attachments ?? [], docsOnly: t.docsOnly ?? false,
      connectors: Array.isArray(t.connectors) ? t.connectors : undefined,
      mode: t.mode === "research" ? "research" : "default",
      model: typeof t.model === "string" ? t.model : null, effort: typeof t.effort === "string" ? t.effort : null,
      savedAt: t.savedAt, conversationId: t.conversationId ?? null,
    }
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

/** One line explaining a security notice to the person, by layer. */
function securityTitle(n: SecurityNotice): string {
  switch (n.layer) {
    case "input": return n.action === "throttled" ? "Your message was flagged; further suspicious messages are being limited." : "Your message contained instruction-like text; it was handled as a normal question."
    case "tool_result": return `Content from ${toolName(n.source)} looked like instructions to the assistant. It was treated as data, not followed.`
    case "action": return n.action === "denied"
      ? `A call to ${toolName(n.source)} was blocked: it would have sent protected data out.`
      : `Because earlier content was suspicious, ${toolName(n.source)} now needs your approval.`
    case "output": return "Part of the answer was removed before showing it (possible data leak)."
    default: return "Security notice"
  }
}

/**
 * The conversation the server put the latest run in.
 *
 * On a first message the client sends no id and the backend creates one, naming
 * it on the `done` event (or on `approval_required`, since a paused run never
 * reaches `done`). This is how the tab learns it, so every later turn continues
 * the same chat instead of starting another.
 */
function conversationIdFrom(messages: UIMessage[]): string | null {
  for (let i = messages.length - 1; i >= 0; i--) {
    const parts = messages[i].parts as Part[]
    for (let j = parts.length - 1; j >= 0; j--) {
      const p = parts[j]
      if (p.type !== "data-run" && p.type !== "data-approval" && p.type !== "data-choice") continue
      const id = (p.data as { conversationId?: unknown } | undefined)?.conversationId
      if (typeof id === "string" && id) return id
    }
  }
  return null
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
  if (tool === "gmail__send_message" || tool === "gmail__create_draft") {
    // what will leave (or be saved to) the user's mailbox, shown as a Gmail compose window
    return (
      <div>
        <div className="h-muted" style={{ fontSize: 12, marginBottom: 6 }}>
          {tool === "gmail__send_message" ? "This email will be SENT from your Gmail:" : "This will be saved to your Gmail drafts (not sent):"}
        </div>
        <GmailCompose status="pending" to={String(args.to ?? "")} cc={typeof args.cc === "string" ? args.cc : null}
          subject={String(args.subject ?? "")} body={String(args.body ?? "")} />
      </div>
    )
  }
  if (tool === "calendar__create_event") {
    return (
      <GoogleCard ui={{ kind: "calendar_events", created: false, events: [{ summary: String(args.summary ?? ""), start: String(args.start ?? ""), end: String(args.end ?? ""),
        all_day: String(args.start ?? "").length === 10, location: typeof args.location === "string" ? args.location : null,
        attendees: Array.isArray(args.attendees) ? (args.attendees as string[]) : [], description: typeof args.description === "string" ? args.description : "" }] }} />
    )
  }
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
  // Deep research: multi-step, cited, bigger budget (see RESEARCH_INSTRUCTION on the backend).
  const [mode, setMode] = useState<"default" | "research">("default")
  // Connectors on for this conversation: restored with the thread, else from
  // the tab (the landing page may have switched some on before the first send).
  const [connectors, setConnectorsState] = useState<string[]>([])
  const setConnectors = useCallback((next: string[]) => { setConnectorsState(next); writeConnectors(next) }, [])
  // null = let the server pick its default model / effort.
  const [model, setModel] = useState<string | null>(null)
  const [effort, setEffort] = useState<string | null>(null)
  // The server-side conversation. null means "not created yet": the first send
  // goes up without one and the backend names the conversation on `done`.
  const [conversationId, setConversationId] = useState<string | null>(null)
  // What every send carries alongside the text. conversationId is how the
  // server knows which transcript to load, so it has to be in here.
  const runOptions = useMemo(
    () => ({ docsOnly, model, effort, connectors, mode, conversationId }),
    [docsOnly, model, effort, connectors, mode, conversationId])

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

  // `?c=<id>` opens a specific conversation (a click in the Chats rail). It is
  // the one thing that can point this tab at a chat it has never shown, so it
  // wins over the tab's own remembered conversation.
  const requestedConv = searchParams.get("c")
  const userId = session?.user?.id ?? null
  // sessionStorage slot for whichever conversation is showing. It is a cache:
  // the server owns the transcript, this just avoids a blank screen.
  const storageKey = userId ? slotKey(userId, conversationId) : null
  const restoredRef = useRef(false)
  // Arriving with `?q=` is a hand-off from the landing page ("Draft a note",
  // "Check the web", a typed question): that is a *new* conversation, so the
  // tab starts clean instead of appending to whatever it last showed. Captured
  // once at mount — the URL loses `q` right after sending, and a plain refresh
  // (no `q`) must still restore.
  const handoffRef = useRef(Boolean(q))
  // False only on the first run of the conversation effect below, so a `?q=`
  // hand-off is honoured once and a later rail click is not mistaken for one.
  const switchedRef = useRef(false)
  // Set once the tab's connector selection has been read, so the handed-over
  // ?q= send below goes up with the connectors the landing page switched on.
  const [tabReady, setTabReady] = useState(false)
  const [hydrating, setHydrating] = useState(false)
  // The save effect below must not run before the restore effect has put the
  // cached messages back: on mount `messages` is [], and saving that would
  // erase the very thread we are about to restore.
  const [restored, setRestored] = useState(false)

  // Tab-level preferences, once.
  useEffect(() => {
    if (!userId || restoredRef.current) return
    restoredRef.current = true
    setConnectorsState(readConnectors())
    setMode(readResearchMode() ? "research" : "default")
    setTabReady(true)
  }, [userId])

  // Which conversation is on screen. This re-runs whenever `?c=` changes, not
  // just at mount: clicking a row in the Chats rail is a query-string change on
  // an already-mounted page, so a mount-only effect would ignore it.
  useEffect(() => {
    if (!userId) return

    // An explicit ?c= wins; otherwise the one this tab was last on; otherwise
    // none (a fresh chat). A `?q=` hand-off from the landing page is always a
    // new conversation, but only for the load it arrived on.
    const handoff = handoffRef.current && !switchedRef.current
    switchedRef.current = true
    const target = requestedConv ?? (handoff ? null : readActive(userId))
    // Nothing to show: clear the thread so a switch does not leave the previous
    // conversation on screen while the new one loads. This effect's whole job is
    // to sync React state from the URL and sessionStorage, which is the case the
    // rule exempts; the cascade it warns about is bounded by `switchedRef` and
    // by the guard at the top.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setRestored(false)
    if (handoff) {
      clearThread(slotKey(userId, null))
      writeActive(userId, null)
      setConversationId(null)
      setRestored(true)
      return
    }
    setConversationId(target)
    writeActive(userId, target)
    setMessages([])
    setResolved({})

    // Paint the cache first if this tab has one, so a refresh is instant.
    // `target` may still be null -- a conversation whose first run never
    // finished has no id yet, and its thread lives in the "new" slot. That is
    // exactly the navigate-away-mid-answer case, so it must be restored too.
    const saved = loadThread(slotKey(userId, target))
    if (saved) {
      setMessages(saved.messages)
      // Restoring is the one place state is synced from an external store on
      // mount; the lint rule is about cascading renders.
      setResolved(saved.resolved)
      setAttachments((a) => (a.length ? a : saved.attachments))
      setDocsOnly(Boolean(saved.docsOnly))
      if (saved.mode) setMode(saved.mode)
      if (saved.connectors) setConnectorsState(saved.connectors)
      setModel(saved.model ?? null)
      setEffort(saved.effort ?? null)
    }
    // Batched with the restore above, so the save effect's first run already
    // sees the restored messages rather than the empty initial state.
    setRestored(true)
    // Nothing server-side to reconcile against until the conversation exists.
    if (!target) return
    // Then reconcile with the server, which is the actual record. This is what
    // makes a chat resumable in a tab that has never seen it — and on another
    // device, where there is no cache at all.
    if (!saved) setHydrating(true)
    const cachedCount = saved?.messages.length ?? 0
    let alive = true
    fetch(`/api/conversations/${target}`, { signal: AbortSignal.timeout(15_000) })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((detail: ConversationDetail) => {
        if (!alive) return
        const rebuilt = toUIMessages(detail.messages ?? [])
        // Only take the server's copy when it actually has more than this tab
        // does. The cache can legitimately hold something the transcript does
        // not: a run cut short mid-answer keeps its partial text and its Retry
        // here, and the server only stores a turn once it completes. Adopting a
        // shorter transcript would silently throw that away.
        if (rebuilt.length > cachedCount) setMessages(rebuilt)
        // Settings are safe to take either way — they are the conversation's.
        setModel(detail.model ?? null)
        setEffort(detail.effort ?? null)
        setDocsOnly(Boolean(detail.docs_only))
        setMode(detail.mode === "research" ? "research" : "default")
        if (Array.isArray(detail.connectors)) setConnectorsState(detail.connectors)
      })
      .catch(() => { /* the cache (or an empty page) is what the user gets */ })
      .finally(() => { if (alive) setHydrating(false) })
    return () => { alive = false }
  }, [userId, requestedConv, setMessages])

  // Remember which conversation this tab is on, so a refresh comes back to it.
  useEffect(() => {
    if (userId) writeActive(userId, conversationId)
  }, [userId, conversationId])

  const streaming = status === "submitted" || status === "streaming"
  // Save on every change, including mid-answer: if the user navigates away
  // while the agent is still talking, the question (and whatever streamed so
  // far) is there when they come back, flagged as cut short with a Retry.
  useEffect(() => {
    if (!storageKey || !restored) return
    saveThread(storageKey, { messages, resolved, attachments, docsOnly, connectors, mode, model, effort, conversationId })
  }, [storageKey, restored, messages, resolved, attachments, docsOnly, connectors, mode, model, effort, conversationId])

  // The rail is written server-side from the real transcript now (the backend
  // stores the conversation and its episode), so there is nothing to POST from
  // here. `chatsVersion` still bumps once a run finishes so the rail refetches
  // and shows the new (or renamed) chat.
  // Adopt the conversation the server created for a first message, so the next
  // turn carries it and the tab can restore this chat after a refresh.
  const reportedConv = conversationIdFrom(messages)
  useEffect(() => {
    if (!reportedConv || reportedConv === conversationId) return
    // Adopting an id the server just told us about, once — the guard above makes
    // this idempotent, so it cannot cascade.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setConversationId(reportedConv)
    // The thread moves from the "new" slot to this conversation's own slot;
    // drop the old one so it cannot resurrect into the next fresh chat.
    if (userId) clearThread(slotKey(userId, null))
  }, [reportedConv, conversationId, userId])

  const runsDone = countRuns(messages)
  const [chatsVersion, setChatsVersion] = useState(0)
  const seenRunsRef = useRef(0)
  useEffect(() => {
    if (runsDone === 0 || runsDone <= seenRunsRef.current) return
    seenRunsRef.current = runsDone
    setChatsVersion((v) => v + 1)
  }, [runsDone])

  // Send the handed-over question once, then drop it from the URL so a
  // refresh (or back/forward) does not send it again.
  const sentRef = useRef(false)
  useEffect(() => {
    if (!q || sentRef.current || authStatus !== "authenticated" || !tabReady) return
    sentRef.current = true
    sendMessage({ text: q }, { body: runOptions })
    router.replace("/chat")   // drop ?q= (and ?doc=) so a refresh does not resend
  }, [q, sendMessage, authStatus, router, runOptions, tabReady])
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
      sendMessage({ text }, { body: runOptions })
      setInput("")
    } else {
      setSignIn({ open: true, mode: "signin", reason: "Sign in to ask the agent." })
    }
  }, [pendingText, authStatus, sendMessage, runOptions])

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
    sendMessage({ text }, { body: runOptions })
    setInput("")
  }

  const retryLast = () => {
    setNotice(null)
    clearError()
    void regenerate({ body: runOptions })
  }

  const newChat = () => {
    if (streaming) stop()
    setMessages([])
    // null, not a fresh client id: the backend creates the conversation on the
    // first send and tells us its id on `done`.
    setConversationId(null)
    seenRunsRef.current = 0
    setResolved({})
    setAttachments([])
    setUploadError(null)
    setNotice(null)
    clearError()
    // Drop only the "new" slot; the previous conversation's cache stays so
    // reopening it from the rail is still instant.
    if (userId) clearThread(slotKey(userId, null))
    // A stale ?c= would drag the tab straight back into the old chat.
    if (requestedConv) router.replace("/chat")
  }

  /** Switch this tab to another conversation (a click in the Chats rail). */
  const openConversation = (id: string) => {
    if (id === conversationId) return
    if (streaming) stop()
    router.push(`/chat?c=${id}`)
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
    // An output-guard notice carries the guarded answer: the text streamed
    // before it is superseded and not shown.
    const guardedAt = parts.findIndex((p) => p.type === "data-security" && (p.data as SecurityNotice).answer !== undefined)
    parts.forEach((part, i) => {
      const key = `${msgId}-${i}`
      if (part.type === "text" && guardedAt !== -1 && i < guardedAt) return
      if (part.type === "data-tool") {
        const activity = part.data as ToolActivity
        // ask_user has no result worth showing — the choice card below says it.
        if (activity.tool !== "ask_user") group.push({ kind: "tool", key, activity })
        // A Workspace result renders as a Google-styled card right after its step.
        if (activity.status === "done" && isGoogleUi(activity.ui)) {
          flush(false)
          out.push(<GoogleCard key={`${key}-card`} ui={activity.ui} />)
        }
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
    if (part.type === "data-security") {
      const n = part.data as SecurityNotice
      return (
        <div key={key} className="h-surface" role="status" data-testid="security-notice" data-layer={n.layer} data-severity={n.severity}
          style={{ padding: "10px 12px", fontSize: 12, margin: "6px 0", display: "flex", gap: 10, alignItems: "flex-start",
                   borderColor: n.severity === "high" ? "var(--err)" : "var(--surface-border)" }}>
          <i className="ti ti-shield-exclamation" style={{ fontSize: 15, marginTop: 1, color: n.severity === "high" ? "var(--err)" : "var(--fg)" }} />
          <div style={{ minWidth: 0 }}>
            <div style={{ fontWeight: 500 }}>{securityTitle(n)}</div>
            {n.reasons.length > 0 && <div className="h-muted" style={{ marginTop: 2, wordBreak: "break-word" }}>{n.reasons.join(" · ")}</div>}
            {n.answer !== undefined && <div style={{ marginTop: 8 }}><AnswerText text={n.answer} /></div>}
          </div>
        </div>
      )
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
      {authStatus === "authenticated" && <ChatsPanel refreshKey={chatsVersion} onUnauthorized={onChatsUnauthorized} onOpen={openConversation} activeId={conversationId} />}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
      <Conversation className="flex-1">
        <ConversationContent className="mx-auto min-h-full w-full max-w-3xl px-5 py-6" data-testid="thread">
          {messages.length === 0 && hydrating ? (
            /* Opening a chat this tab has never shown (from the rail, or on
               another device) — there is no cache to paint, so say so rather
               than flash "Ask anything" over someone's existing conversation. */
            <div className="flex flex-1 flex-col items-center justify-center gap-3 p-8 text-center" data-testid="chat-loading">
              <HangulSigil size={40} />
              <p className="h-muted" style={{ fontSize: 13 }}>Loading this conversation…</p>
            </div>
          ) : messages.length === 0 ? (
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
            <button
              type="button"
              className="h-chip"
              data-testid="research-mode"
              aria-pressed={mode === "research"}
              onClick={() => setMode((m) => { const next = m === "research" ? "default" : "research"; writeResearchMode(next === "research"); return next })}
              title="Deep research: plan, several searches (documents, web, arXiv), numbered citations and a sources list"
              style={mode === "research" ? { background: "var(--solid-bg)", color: "var(--solid-fg)", borderColor: "var(--solid-bg)" } : undefined}
            >
              <i className="ti ti-telescope" style={{ fontSize: 12, marginRight: 5 }} />
              Deep research
            </button>
            <ConnectorChips keys={connectors} onChange={setConnectors} />
            {/* Which model answers and how hard it thinks; both go up with every send. */}
            <ModelPicker
              model={model}
              effort={effort}
              disabled={streaming}
              onChange={(m, e) => { setModel(m); setEffort(e) }}
            />
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
              connectors={connectors}
              onConnectorsChange={setConnectors}
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
