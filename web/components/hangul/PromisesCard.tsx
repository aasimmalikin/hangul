"use client"

import Link from "next/link"
import { useEffect, useState } from "react"
import { MicButton } from "@/components/hangul/MicButton"

/**
 * Kept your word, on Today: what the user owes (replies they owe and promises
 * they made), what's owed to them (late ones first, with Chase), and, after a
 * meeting, "was anything promised?" answered with a line or a voice note.
 * Backed by GET /today's `promises` and `replies` and /api/promises/*.
 */

export type PromiseRow = {
  id: number; direction: "mine" | "theirs"; what: string; who: string; who_email: string; due_on: string | null
  last_contact_at?: string | null; late?: boolean; overdue?: boolean
}
export type Asking = { id: string; summary: string; people: Array<{ name: string; email: string }> }
export type Promised = { mine: PromiseRow[]; theirs: PromiseRow[]; counts: { mine: number; theirs: number }; asking: Asking[] }
type Reply = { thread_id: string; from: string; subject: string; waiting_days: number }

const sender = (from: string) => (from.match(/^\s*"?([^"<]*?)"?\s*</)?.[1] || from.replace(/@.*/, "")).trim()

export function dueLabel(due: string | null): string {
  if (!due) return ""
  const d = new Date(`${due}T12:00:00`)
  const today = new Date(); today.setHours(12, 0, 0, 0)
  const days = Math.round((d.getTime() - today.getTime()) / 86_400_000)
  if (days === 0) return "today"
  if (days === 1) return "tomorrow"
  if (days === -1) return "yesterday"
  if (days < 0) return `${-days} days late`
  return d.toLocaleDateString(undefined, days < 7 ? { weekday: "short" } : { day: "numeric", month: "short" })
}

const names = (a: Asking) => {
  const n = a.people.map((p) => p.name)
  return n.length <= 1 ? (n[0] ?? "them") : `${n.slice(0, -1).join(", ")} and ${n[n.length - 1]}`
}

export function PromisesCard({ promised, replies, onAsk }: {
  promised: Promised | null | undefined
  replies: Reply[] | null | undefined
  onAsk: (text: string) => void
}) {
  const [mine, setMine] = useState<PromiseRow[]>(promised?.mine ?? [])
  const [theirs, setTheirs] = useState<PromiseRow[]>(promised?.theirs ?? [])
  const [asking, setAsking] = useState<Asking[]>(promised?.asking ?? [])
  const [text, setText] = useState("")
  const [saving, setSaving] = useState(false)
  const [note, setNote] = useState<string | null>(null)
  const [upgrade, setUpgrade] = useState(false)
  const owed = replies ?? []
  const meeting = asking[0]

  if (!meeting && mine.length === 0 && theirs.length === 0 && owed.length === 0 && !note) return null

  const kept = async (p: PromiseRow) => {
    setMine((x) => x.filter((q) => q.id !== p.id))
    setTheirs((x) => x.filter((q) => q.id !== p.id))
    await fetch(`/api/promises/${p.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status: "done" }) }).catch(() => null)
  }
  const chase = async (p: PromiseRow) => {
    const res = await fetch(`/api/promises/${p.id}/chase`, { method: "POST" }).catch(() => null)
    if (res?.status === 402) { setUpgrade(true); return }
    const body = res?.ok ? await res.json().catch(() => null) : null
    if (body?.prompt) {
      setTheirs((x) => x.map((q) => (q.id === p.id ? { ...q, late: false } : q)))
      onAsk(body.prompt)
    }
  }
  const capture = async (said: string) => {
    if (!said.trim() || !meeting) return
    setSaving(true)
    const res = await fetch("/api/promises/capture", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: said, meeting_id: meeting.id }) }).catch(() => null)
    setSaving(false)
    if (res?.status === 402) { setUpgrade(true); return }
    const body = res?.ok ? await res.json().catch(() => null) : null
    if (!body) { setNote("Couldn't save that just now. Try again."); return }
    const found: PromiseRow[] = body.promises ?? []
    setMine((x) => [...found.filter((p) => p.direction === "mine"), ...x])
    setTheirs((x) => [...found.filter((p) => p.direction === "theirs"), ...x])
    setAsking((x) => x.slice(1))
    setText("")
    setNote(found.length ? `Kept ${found.length} promise${found.length > 1 ? "s" : ""} from “${meeting.summary}”.`
      : "I didn't hear a promise in that. Nothing kept.")
  }
  const nothing = async () => {
    if (!meeting) return
    setAsking((x) => x.slice(1))
    await fetch(`/api/promises/meetings/${encodeURIComponent(meeting.id)}/skip`, { method: "POST" }).catch(() => null)
  }

  const row = (p: PromiseRow) => (
    <div key={p.id} className="h-word-row" data-testid={`promise-${p.id}`}>
      <span style={{ flex: 1, minWidth: 0 }}>
        <span className="h-word-what">{p.what}</span>
        <span className="h-muted" style={{ fontSize: 11 }}>
          {p.direction === "mine" ? (p.who ? ` · for ${p.who}` : "") : ` · ${p.who || p.who_email || "someone"}`}
          {p.due_on ? ` · ${dueLabel(p.due_on)}` : ""}
          {p.direction === "theirs" && p.last_contact_at ? " · wrote back" : ""}
        </span>
      </span>
      {p.direction === "theirs" && p.late && (
        <button className="h-btn-ghost h-word-btn" data-testid={`promise-chase-${p.id}`} onClick={() => void chase(p)}>Chase</button>
      )}
      <button className="h-btn-ghost h-word-btn" aria-label={`Kept: ${p.what}`} data-testid={`promise-kept-${p.id}`}
        onClick={() => void kept(p)}>Kept</button>
    </div>
  )

  const youOwe = owed.length + (promised?.counts.mine ?? mine.length)
  return (
    <section className="h-surface h-word" data-testid="today-promises" id="promises">
      <div className="h-word-head h-muted">
        <i className="ti ti-heart-handshake" style={{ fontSize: 15, color: "var(--fg)" }} />
        <span style={{ flex: 1 }}>Your word</span>
        <Link href="/kept" className="h-muted" style={{ fontSize: 11 }}>All</Link>
      </div>

      {meeting && (
        <form className="h-word-ask" data-testid="promise-ask" onSubmit={(e) => { e.preventDefault(); void capture(text) }}>
          <div style={{ fontSize: 13 }}>
            How did <b style={{ fontWeight: 500 }}>{meeting.summary}</b> with {names(meeting)} go? Was anything promised?
          </div>
          <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
            <input className="h-input" value={text} onChange={(e) => setText(e.target.value)} disabled={saving}
              placeholder="“I'll send the deck Friday, Priya shares the numbers”" aria-label="What was promised"
              data-testid="promise-ask-input" style={{ flex: 1, minWidth: 0, height: 32, fontSize: 13 }} />
            <MicButton onText={(t) => void capture(t)} disabled={saving} />
          </div>
          <div style={{ display: "flex", gap: 6 }}>
            <button className="h-btn-ghost h-word-btn" type="submit" disabled={saving || !text.trim()} data-testid="promise-ask-save">
              {saving ? "Keeping…" : "Keep it"}
            </button>
            <button className="h-btn-ghost h-word-btn" type="button" onClick={() => void nothing()} data-testid="promise-ask-nothing">
              Nothing promised
            </button>
          </div>
        </form>
      )}
      {note && <div className="h-muted" style={{ fontSize: 12 }} data-testid="promise-note">{note}</div>}
      {upgrade && (
        <Link href="/billing?upgrade=plus" style={{ fontSize: 12, color: "var(--link)" }} data-testid="promise-upgrade">
          Catching promises after meetings and chasing them is part of Plus →
        </Link>
      )}

      {(mine.length > 0 || owed.length > 0) && (
        <div className="h-word-group" data-testid="promises-mine">
          <div className="h-word-label">You owe{youOwe > 0 ? ` · ${youOwe}` : ""}</div>
          {mine.slice(0, 3).map(row)}
          {owed.slice(0, Math.max(1, 3 - mine.length)).map((r) => (
            <a key={r.thread_id} href={`https://mail.google.com/mail/u/0/#inbox/${r.thread_id}`} target="_blank" rel="noreferrer"
              className="h-word-row" data-testid="today-reply" style={{ color: "var(--fg)", textDecoration: "none" }}>
              <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                <span className="h-word-what">A reply to {sender(r.from)}</span>
                <span className="h-muted" style={{ fontSize: 11 }}> · {r.subject} · {r.waiting_days <= 1 ? "1 day" : `${r.waiting_days} days`}</span>
              </span>
            </a>
          ))}
          {owed.length > 0 && (
            <button className="h-btn-ghost h-word-btn" style={{ alignSelf: "flex-start" }} data-testid="today-draft-replies"
              onClick={() => onAsk("Draft short replies to the emails I owe a reply to, starting with the one waiting longest.")}>
              Draft replies →
            </button>
          )}
        </div>
      )}

      {theirs.length > 0 && (
        <div className="h-word-group" data-testid="promises-theirs">
          <div className="h-word-label">Owed to you · {promised?.counts.theirs ?? theirs.length}</div>
          {theirs.slice(0, 3).map(row)}
        </div>
      )}
    </section>
  )
}

/** Next up's prep line: what's open with the people in this meeting. */
export function MeetingPrep({ promises }: { promises?: Array<{ id: number; direction: string; what: string; who: string }> }) {
  if (!promises?.length) return null
  return (
    <div className="h-word-prep" data-testid="meeting-prep">
      {promises.slice(0, 2).map((p) => (
        <span key={p.id}>{p.direction === "mine" ? `You owe ${p.who || "them"}: ` : `${p.who || "They"} owes you: `}{p.what}</span>
      ))}
    </div>
  )
}

/** Settings: whether Hangul reads the user's email for promises (Plus; on by default). */
export function PromiseEmailToggle() {
  const [state, setState] = useState<{ on: boolean; allowed: boolean } | null>(null)
  useEffect(() => {
    let alive = true
    void fetch("/api/promises", { cache: "no-store" }).then((r) => (r.ok ? r.json() : null)).then((b) => {
      if (alive && b) setState({ on: Boolean(b.email_on), allowed: Boolean(b.access?.email) })
    }).catch(() => null)
    return () => { alive = false }
  }, [])
  if (!state) return null
  const flip = async (on: boolean) => {
    setState({ ...state, on })
    const res = await fetch("/api/promises/settings", { method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email_on: on }) }).catch(() => null)
    if (!res?.ok) setState({ ...state })
  }
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }} data-testid="promise-email-setting">
      <label style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 13, cursor: state.allowed ? "pointer" : "default" }}>
        <input type="checkbox" checked={state.on && state.allowed} disabled={!state.allowed} onChange={(e) => void flip(e.target.checked)}
          data-testid="promise-email-toggle" style={{ width: 15, height: 15, accentColor: "var(--fg)" }} />
        Catch promises in my email
      </label>
      {!state.allowed && (
        <Link href="/billing?upgrade=plus" style={{ fontSize: 12, color: "var(--link)" }}>Reading email for promises is part of Plus →</Link>
      )}
    </div>
  )
}
