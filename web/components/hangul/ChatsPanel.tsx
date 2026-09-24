"use client"

import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { failureFromResponse, type ApiFailure } from "@/lib/apiError"

/**
 * One conversation, from GET /api/conversations. These are the real,
 * server-owned conversations now (not the client-written `episodes` summaries),
 * so a row can be reopened — `onOpen` below.
 */
export type ChatItem = {
  id: string
  title: string
  /** Rolling summary of the older turns; "" until a chat outgrows its window. */
  preview: string
  message_count: number
  created_at: string
  updated_at: string
}

// Rail width: dragged by the user, remembered per browser. Bounded so it can
// neither vanish nor swallow the conversation.
const WIDTH_KEY = "hangul:chats-width"
const WIDTH_DEFAULT = 264
const WIDTH_MIN = 200
const WIDTH_MAX = 480
const clampWidth = (w: number) => Math.min(WIDTH_MAX, Math.max(WIDTH_MIN, Math.round(w)))

// ------------------------------------------------------------------ dates

/** Local calendar day as YYYY-MM-DD — what the date filter compares. */
function dayOf(d: Date) {
  const p = (n: number) => String(n).padStart(2, "0")
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}
const todayKey = () => dayOf(new Date())
const yesterdayKey = () => { const d = new Date(); d.setDate(d.getDate() - 1); return dayOf(d) }

function when(iso: string) {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ""
  const day = dayOf(d)
  const time = d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })
  if (day === todayKey()) return `today · ${time}`
  if (day === yesterdayKey()) return `yesterday · ${time}`
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" })
}

/** The date filter behind the settings button: everything, today, yesterday, or one chosen day. */
export type DateFilter = { kind: "all" } | { kind: "today" } | { kind: "yesterday" } | { kind: "custom"; date: string }

function filterLabel(f: DateFilter) {
  if (f.kind === "today") return "Today"
  if (f.kind === "yesterday") return "Yesterday"
  if (f.kind === "custom") return f.date ? new Date(`${f.date}T00:00`).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" }) : "Custom date"
  return ""
}

function applyFilter(items: ChatItem[], f: DateFilter) {
  if (f.kind === "all") return items
  const key = f.kind === "today" ? todayKey() : f.kind === "yesterday" ? yesterdayKey() : f.date
  if (!key) return items
  return items.filter((m) => dayOf(new Date(m.updated_at)) === key)
}

// -------------------------------------------------------------------- rows

/**
 * One conversation: the user's query (one line, "…" when long) and when.
 * The model's answer is deliberately not shown here — it is in "View all".
 * The ⋯ button only shows on hover (or while its menu is open) so the list
 * reads as plain text until the user reaches for it.
 */
function ChatRow({ item, open, onToggle, onDelete, onOpen, active, deleting }: {
  item: ChatItem
  open: boolean
  onToggle: () => void
  onDelete: () => void
  /** Reopen this conversation. Absent on pages that cannot navigate to a chat. */
  onOpen?: () => void
  active?: boolean
  deleting: boolean
}) {
  return (
    <li className={`h-memory-item${open ? " is-open" : ""}${active ? " is-active" : ""}`} data-testid="chats-item" style={{ opacity: deleting ? 0.5 : 1 }}>
      <div style={{ display: "flex", alignItems: "flex-start", gap: 8 }}>
        <i className="ti ti-message" style={{ fontSize: 13, color: "var(--muted)", marginTop: 2, flexShrink: 0 }} />
        {/* The title is the button: the whole row would swallow the ⋯ menu. */}
        <button
          type="button"
          onClick={onOpen}
          disabled={!onOpen || deleting}
          aria-current={active ? "true" : undefined}
          data-testid="chats-open"
          aria-label={onOpen ? `Open "${item.title}"` : undefined}
          style={{ flex: 1, minWidth: 0, textAlign: "left", background: "none", border: 0, padding: 0,
                   cursor: onOpen ? "pointer" : "default", color: "inherit", font: "inherit" }}
        >
          {/* The tooltip stays on the title itself: it is the element that gets
              cut with an ellipsis, so it is what the full text belongs to. */}
          <div data-testid="chats-title" title={item.title} style={{ fontSize: 13, lineHeight: 1.4, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{item.title}</div>
          <div style={{ fontSize: 11, marginTop: 2, color: "var(--faint)" }}>{when(item.updated_at)}</div>
        </button>
        <button
          type="button"
          className="h-memory-dots"
          aria-label="Chat options"
          aria-haspopup="menu"
          aria-expanded={open}
          onClick={(e) => { e.stopPropagation(); onToggle() }}
          disabled={deleting}
        >
          <i className="ti ti-dots" style={{ fontSize: 15 }} />
        </button>
      </div>
      {open && (
        <div className="h-popover" role="menu" style={{ position: "absolute", right: 6, top: 30, minWidth: 140, zIndex: 20, padding: 4 }}>
          <button type="button" role="menuitem" className="h-menu-danger" onClick={onDelete} data-testid="chats-delete">
            <i className="ti ti-trash" style={{ fontSize: 14 }} />
            Delete
          </button>
        </div>
      )}
    </li>
  )
}

// ----------------------------------------------------------------- history

/**
 * "View all": every conversation, with its transcript, in a dialog over the
 * page. Same scrim/dialog surfaces as the sign-in modal, just wider and
 * left-aligned because it is a list, not a prompt.
 */
function HistoryDialog({ items, filter, onClose, onOpen }: { items: ChatItem[]; filter: DateFilter; onClose: () => void; onOpen?: (id: string) => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose() }
    document.addEventListener("keydown", onKey)
    return () => document.removeEventListener("keydown", onKey)
  }, [onClose])
  const label = filterLabel(filter)
  return (
    <div className="h-scrim" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }} data-testid="chats-history">
      <div className="h-dialog h-dialog-wide" role="dialog" aria-modal="true" aria-label="All chats">
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
          <span className="h-display" style={{ fontSize: 18 }}>All chats</span>
          <span className="h-muted" style={{ fontSize: 12 }}>{items.length}{label ? ` · ${label}` : ""}</span>
          <button type="button" className="h-btn-ghost" onClick={onClose} aria-label="Close" style={{ marginLeft: "auto", padding: 6 }}>
            <i className="ti ti-x" style={{ fontSize: 15 }} />
          </button>
        </div>
        <div className="h-sidebar-scroll" style={{ maxHeight: "70vh", display: "flex", flexDirection: "column", gap: 10, paddingRight: 4 }}>
          {items.length === 0 && (
            <p className="h-muted" style={{ fontSize: 13, margin: "8px 0" }}>{label ? `No chats on ${label.toLowerCase()}.` : "No chats yet."}</p>
          )}
          {items.map((m) => (
            <article key={m.id} data-testid="chats-history-item" style={{ background: "var(--surface)", border: "0.5px solid var(--surface-border)", borderRadius: 12, padding: "10px 12px" }}>
              <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 6 }}>
                <span style={{ fontSize: 13, fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{m.title}</span>
                <span style={{ fontSize: 11, color: "var(--faint)", marginLeft: "auto", flexShrink: 0 }}>{when(m.updated_at)}</span>
              </div>
              {/* The full transcript lives on the server now; the dialog shows
                  what the rail knows and opens the chat to read the rest. */}
              <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                {m.preview && (
                  <span className="h-muted" style={{ fontSize: 12.5, lineHeight: 1.45, wordBreak: "break-word" }}>{m.preview}</span>
                )}
                <span style={{ fontSize: 11, color: "var(--faint)" }}>
                  {m.message_count} {m.message_count === 1 ? "message" : "messages"}
                </span>
                {onOpen && (
                  <button type="button" className="h-btn-ghost" data-testid="chats-history-open"
                          onClick={() => { onOpen(m.id); onClose() }}
                          style={{ alignSelf: "flex-start", padding: "2px 6px", fontSize: 12, marginTop: 2 }}>
                    Open chat
                  </button>
                )}
              </div>
            </article>
          ))}
        </div>
      </div>
    </div>
  )
}

// ------------------------------------------------------------------ panel

/**
 * "Chats" rail, shown on the landing page and on /chat: the signed-in
 * user's conversations, most recently touched first — just the query, cut
 * with "…" when long — plus a per-item Delete. It fills the whole left side; the
 * list scrolls between a fixed header and footer. It mounts (and fetches)
 * the moment the session becomes authenticated, so it is there right after
 * sign-in.
 *
 * Header actions (visible on hover): refresh, "View all" (the full history
 * with transcripts, in a dialog) and a settings menu that narrows the list
 * to today, yesterday or one chosen date.
 *
 * Conversations are saved by the chat page after every completed run
 * (see saveConversation in app/chat/page.tsx), so by the time the user is
 * back on the landing page the chat they just had is already listed.
 *
 * "Delete" deactivates the row server-side (harness.db.episodes never
 * hard-deletes); once deactivated it is out of this list and out of the
 * agent's `recall_episodes`. The row is removed optimistically and put back
 * if the call fails.
 *
 * `refreshKey` is bumped by the page whenever a conversation was saved, so
 * the rail on /chat updates without a reload.
 */
export function ChatsPanel({ refreshKey = 0, onUnauthorized, onOpen, activeId }: {
  refreshKey?: number
  onUnauthorized?: () => void
  /** Reopen a conversation. Omitted on pages with no chat to open into. */
  onOpen?: (id: string) => void
  /** The conversation currently on screen, highlighted in the list. */
  activeId?: string | null
}) {
  const [items, setItems] = useState<ChatItem[] | null>(null)
  const [error, setError] = useState<ApiFailure | null>(null)
  const [openId, setOpenId] = useState<string | null>(null)
  const [deleting, setDeleting] = useState<string | null>(null)
  const listRef = useRef<HTMLUListElement>(null)

  // --- header: view all + date filter -----------------------------------
  const [history, setHistory] = useState(false)
  const [filter, setFilter] = useState<DateFilter>({ kind: "all" })
  const [settingsOpen, setSettingsOpen] = useState(false)
  const settingsRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!settingsOpen) return
    const onDoc = (e: MouseEvent) => {
      if (settingsRef.current && !settingsRef.current.contains(e.target as Node)) setSettingsOpen(false)
    }
    document.addEventListener("mousedown", onDoc)
    return () => document.removeEventListener("mousedown", onDoc)
  }, [settingsOpen])
  const visible = useMemo(() => applyFilter(items ?? [], filter), [items, filter])
  const closeHistory = useCallback(() => setHistory(false), [])

  // --- resizable width ------------------------------------------------
  const [width, setWidth] = useState(WIDTH_DEFAULT)
  const [dragging, setDragging] = useState(false)
  useEffect(() => {
    // Restore the remembered width after mount (reading it in the initial
    // state would make the server and client render different widths).
    try {
      const saved = Number(localStorage.getItem(WIDTH_KEY))
      // eslint-disable-next-line react-hooks/set-state-in-effect
      if (saved) setWidth(clampWidth(saved))
    } catch { /* private mode */ }
  }, [])
  const commitWidth = (w: number) => {
    const next = clampWidth(w)
    setWidth(next)
    try { localStorage.setItem(WIDTH_KEY, String(next)) } catch { /* ignore */ }
  }
  const startDrag = (e: React.PointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return // left button only
    e.preventDefault()
    const handle = e.currentTarget
    const startX = e.clientX
    const startW = width
    handle.setPointerCapture(e.pointerId)
    setDragging(true)
    document.body.style.cursor = "col-resize"
    document.body.style.userSelect = "none"
    let latest = startW
    const onMove = (ev: PointerEvent) => {
      latest = clampWidth(startW + (ev.clientX - startX))
      setWidth(latest)
    }
    const onUp = () => {
      handle.removeEventListener("pointermove", onMove)
      handle.removeEventListener("pointerup", onUp)
      handle.removeEventListener("pointercancel", onUp)
      document.body.style.cursor = ""
      document.body.style.userSelect = ""
      setDragging(false)
      commitWidth(latest)
    }
    handle.addEventListener("pointermove", onMove)
    handle.addEventListener("pointerup", onUp)
    handle.addEventListener("pointercancel", onUp)
  }

  // --- data -----------------------------------------------------------
  const load = useCallback(async (signal?: AbortSignal) => {
    try {
      const res = await fetch("/api/conversations", { signal: signal ?? AbortSignal.timeout(10_000), cache: "no-store" })
      if (!res.ok) {
        const f = await failureFromResponse(res)
        if (f.code === "unauthorized") onUnauthorized?.()
        setError(f)
        return
      }
      setItems((await res.json()) as ChatItem[])
      setError(null)
    } catch (e) {
      if ((e as Error).name === "AbortError") return
      setError({ code: "network", detail: "Couldn't load your chats." })
    }
  }, [onUnauthorized])

  useEffect(() => {
    const ctrl = new AbortController()
    // Fetch-on-mount / on refreshKey; state is set after the await, not
    // synchronously — the lint rule cannot see through the async call.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load(ctrl.signal)
    return () => ctrl.abort()
  }, [load, refreshKey])

  // Any click outside the open row menu closes it.
  useEffect(() => {
    if (openId === null) return
    const onDoc = (e: MouseEvent) => {
      if (listRef.current && !listRef.current.contains(e.target as Node)) setOpenId(null)
    }
    document.addEventListener("mousedown", onDoc)
    return () => document.removeEventListener("mousedown", onDoc)
  }, [openId])

  const remove = async (id: string) => {
    setOpenId(null)
    const before = items ?? []
    setItems(before.filter((m) => m.id !== id))
    setDeleting(id)
    try {
      const res = await fetch(`/api/conversations/${id}`, { method: "DELETE", signal: AbortSignal.timeout(10_000) })
      // 404 = already gone (another tab): the optimistic removal was right.
      if (!res.ok && res.status !== 404) {
        const f = await failureFromResponse(res)
        if (f.code === "unauthorized") onUnauthorized?.()
        setError(f)
        setItems(before)
      }
    } catch {
      setError({ code: "network", detail: "Couldn't delete that chat." })
      setItems(before)
    } finally {
      setDeleting(null)
    }
  }

  const label = filterLabel(filter)
  const setKind = (kind: "all" | "today" | "yesterday") => { setFilter({ kind }); setSettingsOpen(false) }

  return (
    <aside className="h-sidebar" aria-label="Chats" data-testid="chats-panel" style={{ width }}>
      <section className="h-sidebar-panel" data-testid="chats-section">
      <div className="h-sidebar-head" style={{ display: "flex", alignItems: "center", gap: 6, padding: "12px 10px 8px 14px" }}>
        <span className="h-display" style={{ fontSize: 12 }}>Chats</span>
        {items && items.length > 0 && <span className="h-muted" style={{ fontSize: 12 }}>{visible.length}</span>}

        {/* Actions, revealed when the header is hovered. */}
        <div className="h-sidebar-actions" style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 2 }}>
          <button type="button" className="h-btn-ghost h-tip" data-tip="Refresh" onClick={() => void load()} aria-label="Refresh chats" style={{ padding: 6 }}>
            <i className="ti ti-refresh" style={{ fontSize: 14 }} />
          </button>
          <button type="button" className="h-btn-ghost h-tip" data-tip="View all" onClick={() => setHistory(true)} aria-label="View all chats" data-testid="chats-view-all" style={{ padding: 6 }}>
            <i className="ti ti-arrow-right" style={{ fontSize: 15 }} />
          </button>
          <div ref={settingsRef} style={{ position: "relative" }}>
            <button
              type="button"
              className="h-btn-ghost h-tip"
              data-tip="Sort by date"
              onClick={() => setSettingsOpen((o) => !o)}
              aria-label="Chat settings"
              aria-haspopup="menu"
              aria-expanded={settingsOpen}
              data-testid="chats-settings"
              style={{ padding: 6, color: filter.kind === "all" ? undefined : "var(--fg)" }}
            >
              <i className="ti ti-adjustments-horizontal" style={{ fontSize: 15 }} />
            </button>
            {settingsOpen && (
              <div className="h-popover" role="menu" aria-label="Sort by date" data-testid="chats-sort-menu" style={{ position: "absolute", right: 0, top: 32, minWidth: 190, zIndex: 25, padding: 4 }}>
                <div className="h-muted" style={{ fontSize: 11, padding: "6px 10px 4px", letterSpacing: "0.02em", textTransform: "uppercase" }}>Sort by date</div>
                {([["today", "Today"], ["yesterday", "Yesterday"]] as const).map(([k, text]) => (
                  <button key={k} type="button" role="menuitemradio" aria-checked={filter.kind === k} className={`h-menu-item${filter.kind === k ? " is-active" : ""}`} onClick={() => setKind(k)}>
                    <i className={`ti ${k === "today" ? "ti-calendar-event" : "ti-calendar-minus"}`} style={{ fontSize: 14 }} />
                    {text}
                    {filter.kind === k && <i className="ti ti-check" style={{ fontSize: 13, marginLeft: "auto" }} />}
                  </button>
                ))}
                <button type="button" role="menuitemradio" aria-checked={filter.kind === "custom"} className={`h-menu-item${filter.kind === "custom" ? " is-active" : ""}`} onClick={() => setFilter({ kind: "custom", date: filter.kind === "custom" ? filter.date : "" })}>
                  <i className="ti ti-calendar-search" style={{ fontSize: 14 }} />
                  Custom date
                  {filter.kind === "custom" && <i className="ti ti-check" style={{ fontSize: 13, marginLeft: "auto" }} />}
                </button>
                {filter.kind === "custom" && (
                  <div style={{ padding: "4px 10px 8px" }}>
                    <input
                      type="date"
                      className="h-input"
                      aria-label="Choose a date"
                      data-testid="chats-custom-date"
                      max={todayKey()}
                      value={filter.date}
                      onChange={(e) => setFilter({ kind: "custom", date: e.target.value })}
                      style={{ padding: "6px 8px", fontSize: 13 }}
                      autoFocus
                    />
                  </div>
                )}
                {filter.kind !== "all" && (
                  <>
                    <div style={{ borderTop: "0.5px solid var(--surface-border)", margin: "4px 0" }} />
                    <button type="button" role="menuitem" className="h-menu-item" onClick={() => setKind("all")} data-testid="chats-sort-clear">
                      <i className="ti ti-x" style={{ fontSize: 14 }} />
                      Show all dates
                    </button>
                  </>
                )}
              </div>
            )}
          </div>
        </div>
      </div>

      {label && (
        <div style={{ padding: "0 14px 6px" }}>
          <button type="button" className="h-chip" onClick={() => setKind("all")} title="Clear" data-testid="chats-filter-chip" style={{ padding: "3px 10px", fontSize: 11, display: "inline-flex", alignItems: "center", gap: 5 }}>
            <i className="ti ti-calendar" style={{ fontSize: 12 }} />
            {label}
            <i className="ti ti-x" style={{ fontSize: 11 }} />
          </button>
        </div>
      )}

      <div className="h-sidebar-scroll" style={{ padding: "0 8px" }}>
        {items === null && !error && (
          <p className="h-muted" style={{ fontSize: 12, padding: "6px 6px" }}>Loading…</p>
        )}
        {items && items.length === 0 && !error && (
          <p className="h-muted" style={{ fontSize: 12, padding: "6px 6px", lineHeight: 1.5 }}>
            No chats yet. Ask the agent something and the conversation will show up here.
          </p>
        )}
        {items && items.length > 0 && visible.length === 0 && (
          <p className="h-muted" style={{ fontSize: 12, padding: "6px 6px", lineHeight: 1.5 }} data-testid="chats-filter-empty">
            No chats on {label.toLowerCase()}.
          </p>
        )}
        {visible.length > 0 && (
          <ul ref={listRef} style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 2 }}>
            {visible.map((m) => (
              <ChatRow
                key={m.id}
                item={m}
                open={openId === m.id}
                onToggle={() => setOpenId((o) => (o === m.id ? null : m.id))}
                onDelete={() => void remove(m.id)}
                onOpen={onOpen ? () => onOpen(m.id) : undefined}
                active={activeId === m.id}
                deleting={deleting === m.id}
              />
            ))}
          </ul>
        )}
        {error && (
          <div style={{ fontSize: 12, color: "var(--err)", padding: "6px 6px" }}>
            {error.detail}{" "}
            <button type="button" className="h-btn-ghost" style={{ padding: "2px 6px", fontSize: 12, display: "inline-flex" }} onClick={() => void load()}>Retry</button>
          </div>
        )}
      </div>

      <p className="h-muted" style={{ fontSize: 11, lineHeight: 1.4, margin: 0, padding: "10px 14px 14px", borderTop: "0.5px solid var(--surface-border)" }}>
        Deleting hides a chat from you and the agent; it is kept, inactive, on the server.
      </p>
      </section>

      {/* Drag handle on the right edge: left-click and drag to resize,
          double-click to reset, arrow keys when focused. */}
      <div
        className={`h-sidebar-handle${dragging ? " is-dragging" : ""}`}
        role="separator"
        aria-orientation="vertical"
        aria-label="Resize chats panel"
        aria-valuenow={width}
        aria-valuemin={WIDTH_MIN}
        aria-valuemax={WIDTH_MAX}
        tabIndex={0}
        title="Drag to resize · double-click to reset"
        data-testid="chats-resize"
        onPointerDown={startDrag}
        onDoubleClick={() => commitWidth(WIDTH_DEFAULT)}
        onKeyDown={(e) => {
          if (e.key === "ArrowLeft") { e.preventDefault(); commitWidth(width - 16) }
          if (e.key === "ArrowRight") { e.preventDefault(); commitWidth(width + 16) }
          if (e.key === "Home") { e.preventDefault(); commitWidth(WIDTH_MIN) }
          if (e.key === "End") { e.preventDefault(); commitWidth(WIDTH_MAX) }
        }}
      />

      {history && <HistoryDialog items={visible} filter={filter} onClose={closeHistory} onOpen={onOpen} />}
    </aside>
  )
}
