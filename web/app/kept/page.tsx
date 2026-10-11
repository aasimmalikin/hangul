"use client"

import Link from "next/link"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { useSession } from "next-auth/react"
import { useRouter } from "next/navigation"
import { AppHeader } from "@/components/hangul/AppHeader"
import { SignInModal, type AuthMode } from "@/components/hangul/SignInModal"
import { KeptHolding, type HoldingSection } from "@/components/hangul/KeptHolding"
import { announceKept } from "@/components/hangul/MainNav"

/**
 * /kept — everything the user asked Hangul to do that lasts beyond the reply,
 * in their own words, on one line through time (GET /api/kept):
 *
 *   done ───────────── NOW ───────────── coming
 *   (earlier, today so far)  (needs you, later today, later)
 *
 * Laptop: four lanes left to right with the now line between them. Phone: the
 * same lanes top to bottom, scrolled to the now line on open. The search box
 * (`/` or ⌘K) searches all time, undated things included. Undated things
 * (lists, notes, memories, files) sit in the Holding drawer underneath.
 */

type State = "needs_you" | "coming" | "done" | "kept"
type KeptItem = {
  id: string; kind: string; state: State; did: string; said: string | null; when: string | null
  app: string | null; conversation_id: string | null; ref: Record<string, unknown>
}
type KeptData = {
  now: string; query: string | null; items: KeptItem[]; needs_you: number
  holding: { lists: Record<string, number>; notes: number; memories: number; files: number }
}

const STATE_LABEL: Record<State, string> = { needs_you: "Needs you", coming: "Coming up", done: "Done", kept: "Kept" }
const FILTERS: { key: State | "all"; label: string }[] = [
  { key: "all", label: "All" }, { key: "needs_you", label: "Needs you" }, { key: "coming", label: "Coming up" },
  { key: "done", label: "Done" }, { key: "kept", label: "Kept" },
]

const dayKey = (d: Date) => `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`

function when(iso: string | null, now: Date): string {
  if (!iso) return ""
  const d = new Date(iso)
  const time = d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })
  if (dayKey(d) === dayKey(now)) return time
  const tomorrow = new Date(now); tomorrow.setDate(now.getDate() + 1)
  const yesterday = new Date(now); yesterday.setDate(now.getDate() - 1)
  if (dayKey(d) === dayKey(tomorrow)) return `Tomorrow ${time}`
  if (dayKey(d) === dayKey(yesterday)) return `Yesterday ${time}`
  return `${d.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" })}, ${time}`
}

/** The four lanes of the Day line, oldest first; the now line sits between 2 and 3. */
function lanes(items: KeptItem[], now: Date) {
  const startOfToday = new Date(now); startOfToday.setHours(0, 0, 0, 0)
  const endOfToday = new Date(startOfToday); endOfToday.setDate(endOfToday.getDate() + 1)
  const earlier: KeptItem[] = [], today: KeptItem[] = [], later: KeptItem[] = [], ahead: KeptItem[] = []
  for (const it of items) {
    const t = it.when ? new Date(it.when) : now
    if (it.state === "needs_you") later.unshift(it)            // waiting on the user: right at the now line
    else if (it.state === "done" || t <= now) (t < startOfToday ? earlier : today).push(it)
    else (t < endOfToday ? later : ahead).push(it)
  }
  // needs-you rows first in "later today", newest of them first
  return { earlier, today, later, ahead }
}

async function call(path: string, init?: RequestInit) {
  const res = await fetch(`/api/${path}`, { ...init, cache: "no-store", headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) } })
  if (!res.ok) {
    let detail = `Request failed (${res.status})`
    try { detail = (await res.json()).detail ?? detail } catch {}
    throw new Error(typeof detail === "string" ? detail : "Request failed")
  }
  return res.json().catch(() => ({}))
}

function Row({ it, now, onDone, highlight }: { it: KeptItem; now: Date; onDone: (msg?: string) => void; highlight?: string[] }) {
  const [busy, setBusy] = useState(false)
  const router = useRouter()
  const act = async (fn: () => Promise<unknown>, msg: string) => {
    setBusy(true)
    try { await fn(); onDone(msg) } catch (e) { onDone((e as Error).message) } finally { setBusy(false) }
  }
  const id = it.ref.id as number | undefined
  const chat = it.conversation_id ? `/chat?c=${encodeURIComponent(it.conversation_id)}` : null
  const mark = (text: string) => {
    if (!highlight?.length) return text
    const re = new RegExp(`(${highlight.map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})`, "ig")
    return text.split(re).map((p, i) => (i % 2 ? <mark key={i}>{p}</mark> : p))
  }

  return (
    <article className="h-kept-row" data-state={it.state} data-testid={`kept-${it.id}`}>
      <div className="h-kept-row-top">
        <span className="h-kept-pill" data-state={it.state}>{it.state === "coming" || it.state === "done" ? (it.app ?? STATE_LABEL[it.state]) : STATE_LABEL[it.state]}</span>
        <span className="h-kept-when">{when(it.when, now)}{it.ref.repeats ? " · repeats" : ""}</span>
      </div>
      {it.said
        ? <p className="h-kept-said">{mark(it.said)}</p>
        : null}
      <p className={it.said ? "h-kept-did" : "h-kept-said h-kept-said-plain"}>{mark(it.did)}</p>
      <div className="h-kept-actions">
        {it.kind === "approval" && chat && <Link className="h-btn-solid h-kept-btn" href={chat}>Review</Link>}
        {it.kind === "approval" && (
          <button className="h-btn-ghost h-kept-btn" disabled={busy} type="button"
            onClick={() => void act(() => call("approve", { method: "POST", body: JSON.stringify({ approval_id: it.ref.run_id, decision: "reject" }) }), "Rejected. Nothing was sent.")}>
            Reject
          </button>
        )}
        {it.kind === "reminder" && it.state === "coming" && id != null && (
          <button className="h-btn-ghost h-kept-btn" disabled={busy} type="button"
            onClick={() => void act(() => call(`reminders/${id}`, { method: "DELETE" }), "Reminder cancelled.")}>Cancel</button>
        )}
        {it.kind === "reminder" && it.ref.status === "sent" && id != null && (
          <button className="h-btn-ghost h-kept-btn" disabled={busy} type="button"
            onClick={() => void act(() => call(`reminders/${id}/done`, { method: "POST" }), "Marked done.")}>Mark done</button>
        )}
        {it.kind === "task" && id != null && (
          <button className="h-btn-ghost h-kept-btn" disabled={busy} type="button"
            onClick={() => void act(() => call(`tasks/${id}`, { method: "POST", body: JSON.stringify({ enabled: false }) }), "Paused. Turn it back on in Settings.")}>Pause</button>
        )}
        {it.kind === "todo" && !it.ref.done && id != null && (
          <button className="h-btn-ghost h-kept-btn" disabled={busy} type="button"
            onClick={() => void act(() => call(`lists/items/${id}`, { method: "PATCH", body: JSON.stringify({ done: true }) }), "Ticked off.")}>Tick off</button>
        )}
        {it.kind === "note" && id != null && (
          <button className="h-btn-ghost h-kept-btn" disabled={busy} type="button"
            onClick={() => void act(() => call(`notes/${id}`, { method: "DELETE" }), "Note deleted.")}>Delete</button>
        )}
        {it.kind === "memory" && id != null && (
          <button className="h-btn-ghost h-kept-btn" disabled={busy} type="button"
            onClick={() => void act(() => call(`memory/${id}`, { method: "DELETE" }), "Forgotten.")}>Forget</button>
        )}
        {it.kind === "promise" && it.ref.status === "open" && id != null && (
          <>
            {it.ref.wrote_back ? <span className="h-kept-when">They wrote back</span> : null}
            {it.ref.direction === "theirs" && (
              <button className="h-btn-ghost h-kept-btn" disabled={busy} type="button" data-testid={`kept-chase-${id}`}
                onClick={() => void act(async () => {
                  // the draft (and any send) happens in chat, where it waits for the user's OK
                  const { prompt } = await call(`promises/${id}/chase`, { method: "POST" })
                  router.push(`/chat?q=${encodeURIComponent(prompt)}`)
                }, "Opening the chat…")}>{it.ref.chased ? "Chase again" : "Chase"}</button>
            )}
            <button className="h-btn-ghost h-kept-btn" disabled={busy} type="button" data-testid={`kept-promise-kept-${id}`}
              onClick={() => void act(() => call(`promises/${id}`, { method: "PATCH", body: JSON.stringify({ status: "done" }) }), "Marked kept.")}>Mark kept</button>
            <button className="h-btn-ghost h-kept-btn" disabled={busy} type="button"
              onClick={() => void act(() => call(`promises/${id}`, { method: "PATCH", body: JSON.stringify({ status: "dropped" }) }), "Dropped.")}>Drop</button>
          </>
        )}
        {chat && it.kind !== "approval" && <Link className="h-kept-link" href={chat}>Open the chat</Link>}
      </div>
    </article>
  )
}

function Lane({ title, items, now, onDone, empty, testId }: { title: string; items: KeptItem[]; now: Date; onDone: (m?: string) => void; empty: string; testId: string }) {
  return (
    <section className="h-kept-lane" data-testid={testId}>
      <h2 className="h-kept-lane-title">{title}</h2>
      {items.length === 0 ? <p className="h-kept-empty">{empty}</p> : items.map((it) => <Row key={it.id} it={it} now={now} onDone={onDone} />)}
    </section>
  )
}

export default function KeptPage() {
  const { status: authStatus } = useSession()
  const [signIn, setSignIn] = useState<{ open: boolean; mode: AuthMode }>({ open: false, mode: "signin" })
  const [gateDismissed, setGateDismissed] = useState(false)
  const signInOpen = signIn.open || (authStatus === "unauthenticated" && !gateDismissed)

  const [data, setData] = useState<KeptData | null>(null)
  const [found, setResults] = useState<KeptData | null>(null)
  const [q, setQ] = useState("")
  const [filter, setFilter] = useState<State | "all">("all")
  const [toast, setToast] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [holdingOpen, setHoldingOpen] = useState(false)
  const [nowVisible, setNowVisible] = useState(true)
  const searchRef = useRef<HTMLInputElement>(null)
  const nowRef = useRef<HTMLDivElement>(null)
  const scrolled = useRef(false)

  const load = useCallback(async () => {
    try { setData(await call("kept")); setError(null) } catch (e) { setError((e as Error).message) }
  }, [])

  useEffect(() => {
    if (authStatus !== "authenticated") return
    // Fetch-on-sign-in; state is set after the await (same pattern as /settings).
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load()
  }, [authStatus, load])

  // #holding (the old /lists address) opens the drawer
  useEffect(() => {
    if (typeof window !== "undefined" && window.location.hash.startsWith("#holding")) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setHoldingOpen(true)
      setTimeout(() => document.getElementById("holding")?.scrollIntoView({ block: "start" }), 150)
    }
  }, [])

  // search: debounced, all time
  useEffect(() => {
    const term = q.trim()
    if (!term) return
    const t = setTimeout(async () => {
      try { setResults(await call(`kept?q=${encodeURIComponent(term)}`)) } catch (e) { setError((e as Error).message) }
    }, 250)
    return () => clearTimeout(t)
  }, [q])

  // "/" or ⌘K / Ctrl+K focuses the search
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const typing = e.target instanceof HTMLElement && /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName)
      if ((e.key === "k" && (e.metaKey || e.ctrlKey)) || (e.key === "/" && !typing)) {
        e.preventDefault(); searchRef.current?.focus()
      }
      if (e.key === "Escape" && document.activeElement === searchRef.current) setQ("")
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [])

  // open at the now line (it matters on phones, where the lanes stack)
  useEffect(() => {
    if (!data || scrolled.current || !nowRef.current || window.location.hash) return
    scrolled.current = true
    if (window.matchMedia("(max-width: 720px)").matches) nowRef.current.scrollIntoView({ block: "center" })
  }, [data])

  useEffect(() => {
    const el = nowRef.current
    if (!el || typeof IntersectionObserver === "undefined") return
    const io = new IntersectionObserver(([e]) => setNowVisible(e.isIntersecting))
    io.observe(el)
    return () => io.disconnect()
  }, [data])

  const onDone = (msg?: string) => {
    if (msg) { setToast(msg); setTimeout(() => setToast(null), 3500) }
    void load(); announceKept()
    if (q.trim()) void call(`kept?q=${encodeURIComponent(q.trim())}`).then(setResults).catch(() => null)
  }

  const results = q.trim() ? found : null
  const now = useMemo(() => (data ? new Date(data.now) : new Date()), [data])
  const l = useMemo(() => lanes(data?.items ?? [], now), [data, now])
  const holding = data?.holding
  const listOpen = holding ? Object.values(holding.lists).reduce((a, b) => a + b, 0) : 0
  const words = q.trim().toLowerCase().split(/\s+/).filter((w) => w.length > 2)

  const shown = (results?.items ?? []).filter((i) => filter === "all" || i.state === filter).slice().reverse()
  const counts = (results?.items ?? []).reduce<Record<string, number>>((c, i) => ({ ...c, [i.state]: (c[i.state] ?? 0) + 1 }), {})
  const summary = results
    ? results.items.length === 0
      ? `Nothing matches “${q.trim()}”. Try fewer words.`
      : `${results.items.length} ${results.items.length === 1 ? "thing" : "things"} for “${q.trim()}”: ` +
        (["needs_you", "coming", "done", "kept"] as State[]).filter((s) => counts[s]).map((s) => `${counts[s]} ${STATE_LABEL[s].toLowerCase()}`).join(", ") + "."
    : ""

  const openHolding = (section?: HoldingSection) => {
    setHoldingOpen(true)
    setTimeout(() => document.getElementById(section ? `holding-${section}` : "holding")?.scrollIntoView({ behavior: "smooth", block: "start" }), 80)
  }

  const empty = data && data.items.length === 0

  return (
    <main className="h-has-bottom-nav h-kept" style={{ minHeight: "100vh", display: "flex", flexDirection: "column" }}>
      <AppHeader onSignIn={() => setSignIn({ open: true, mode: "signin" })} onSignUp={() => setSignIn({ open: true, mode: "signup" })} />
      <SignInModal open={signInOpen} mode={signIn.mode} onClose={() => { setGateDismissed(true); setSignIn((s) => ({ ...s, open: false })) }} callbackUrl="/kept" reason="Sign in to see what you've asked Hangul to do." />

      <div className="h-kept-wrap">
        <header className="h-kept-head">
          <div>
            <h1 className="h-display h-kept-title">Kept</h1>
            <p className="h-muted h-kept-sub">
              {data
                ? data.needs_you
                  ? `${data.needs_you} ${data.needs_you === 1 ? "thing needs" : "things need"} you · everything you asked Hangul to do`
                  : "Everything you asked Hangul to do, and what happened."
                : "Loading…"}
            </p>
          </div>
          <form className="h-kept-search" role="search" onSubmit={(e) => e.preventDefault()}>
            <i className="ti ti-search" aria-hidden />
            <input ref={searchRef} id="kept-search" data-testid="kept-search" value={q} onChange={(e) => setQ(e.target.value)}
              placeholder="What did I ask about…" aria-label="Search everything you asked" maxLength={200} autoComplete="off" />
            {q ? <button type="button" className="h-btn-ghost" aria-label="Clear search" onClick={() => setQ("")} style={{ padding: "2px 6px" }}><i className="ti ti-x" /></button>
              : <kbd className="h-kept-kbd">/</kbd>}
          </form>
        </header>

        {error && <div className="h-surface" style={{ padding: 12, fontSize: 13, color: "var(--err)" }} role="alert">{error}</div>}

        {results ? (
          <section className="h-kept-results" data-testid="kept-results" aria-live="polite">
            <p className="h-kept-summary" data-testid="kept-summary">{summary}</p>
            <div className="h-kept-filters" role="group" aria-label="Show">
              {FILTERS.map((f) => (
                <button key={f.key} type="button" className="h-kept-chip" aria-pressed={filter === f.key} onClick={() => setFilter(f.key)}>
                  {f.label}{f.key !== "all" && counts[f.key] ? ` · ${counts[f.key]}` : ""}
                </button>
              ))}
            </div>
            <div className="h-kept-list">
              {shown.map((it) => <Row key={it.id} it={it} now={now} onDone={onDone} highlight={words} />)}
            </div>
          </section>
        ) : empty ? (
          <section className="h-surface h-kept-zero" data-testid="kept-empty">
            <h2 className="h-display" style={{ fontSize: 20, margin: 0, fontWeight: 400 }}>Nothing yet</h2>
            <p className="h-muted" style={{ margin: 0, fontSize: 14 }}>
              When you ask Hangul for something that lasts, it shows up here with your words: “remind me to call mum at 6”,
              “brief me every morning at 8”, “email Priya the deck”.
            </p>
            <Link className="h-btn-solid" href="/chat" style={{ alignSelf: "flex-start" }}>Ask Hangul</Link>
          </section>
        ) : (
          <div className="h-kept-line" data-testid="kept-line">
            <Lane title="Earlier this week" items={l.earlier} now={now} onDone={onDone} empty="Nothing earlier." testId="lane-earlier" />
            <Lane title="Today, so far" items={l.today} now={now} onDone={onDone} empty="Nothing yet today." testId="lane-today" />
            <div className="h-kept-now" ref={nowRef} data-testid="kept-now" aria-label="Now">
              <span>Now · {now.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}</span>
            </div>
            <Lane title="Later today" items={l.later} now={now} onDone={onDone} empty="Nothing else today." testId="lane-later" />
            <Lane title="Coming up" items={l.ahead} now={now} onDone={onDone} empty="Nothing scheduled." testId="lane-ahead" />
          </div>
        )}

        <section id="holding" className="h-kept-drawer" data-testid="kept-holding" style={{ scrollMarginTop: 80 }}>
          <button type="button" className="h-kept-drawer-head" aria-expanded={holdingOpen} onClick={() => setHoldingOpen((o) => !o)}>
            <span>No date: Hangul is holding these</span>
            <i className={`ti ti-chevron-${holdingOpen ? "up" : "down"}`} aria-hidden />
          </button>
          <div className="h-kept-filters">
            <button type="button" className="h-kept-chip" onClick={() => openHolding("lists")}>Lists{listOpen ? ` · ${listOpen} open` : ""}</button>
            <button type="button" className="h-kept-chip" onClick={() => openHolding("notes")}>Notes{holding?.notes ? ` · ${holding.notes}` : ""}</button>
            <button type="button" className="h-kept-chip" onClick={() => openHolding("memories")}>Remembered{holding?.memories ? ` · ${holding.memories}` : ""}</button>
            <button type="button" className="h-kept-chip" onClick={() => openHolding("files")}>Files{holding?.files ? ` · ${holding.files}` : ""}</button>
          </div>
          {holdingOpen && authStatus === "authenticated" && <KeptHolding onChange={() => void load()} />}
        </section>
      </div>

      {!results && !empty && data && !nowVisible && (
        <button type="button" className="h-kept-jump" onClick={() => nowRef.current?.scrollIntoView({ behavior: "smooth", block: "center" })}>
          Back to now
        </button>
      )}
      {toast && <div className="h-kept-toast" role="status">{toast}</div>}
    </main>
  )
}
