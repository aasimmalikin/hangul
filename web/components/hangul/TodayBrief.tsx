"use client"

import Link from "next/link"
import { useCallback, useEffect, useState } from "react"

/**
 * The Today screen: what the user needs to know right now, before they ask.
 * Built from GET /api/today (weather for their city, the rest of today's
 * calendar, reminders and to-dos, approvals waiting on them, important
 * unread mail). Every card is one tap from acting: tick a to-do, dismiss a
 * reminder, open the chat that's waiting, or ask about the inbox.
 */

type Event = { summary: string; start: string; end: string; all_day?: boolean; location?: string | null }
type Brief = {
  greeting: string
  name: string
  date_label: string
  city: string
  weather: { place: string; current: { temp: number; label: string; icon: string }; daily?: Array<{ max: number; min: number; rain_chance: number | null }> } | null
  events: Event[] | null
  emails: Array<{ id: string; from: string; subject: string }> | null
  reminders: Array<{ id: number; text: string; due_at: string; status: string }>
  todos: Array<{ id: number; text: string; list_name: string; done: boolean }>
  approvals: Array<{ run_id: string; conversation_id: string | null; tool: string }>
  connected: string[]
}

const time = (iso: string) => {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })
}
const sender = (from: string) => (from.match(/^\s*"?([^"<]*?)"?\s*</)?.[1] || from.replace(/@.*/, "")).trim()
const APPROVAL_LABEL: Record<string, string> = {
  gmail__send_message: "Send an email", gmail__send_draft: "Send a draft", calendar__create_event: "Add an event",
  calendar__update_event: "Change an event", calendar__delete_event: "Delete an event", sheets__append_rows: "Add rows to a sheet",
  slack__send_message: "Post to Slack", github__create_issue: "Open a GitHub issue", github__comment: "Comment on GitHub",
}

function Tile({ icon, title, children, testId, action }: { icon: string; title: string; children: React.ReactNode; testId: string; action?: React.ReactNode }) {
  return (
    <section className="h-surface" data-testid={testId}
      style={{ padding: "12px 14px", borderRadius: 14, display: "flex", flexDirection: "column", gap: 8, minWidth: 0 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12 }} className="h-muted">
        <i className={`ti ti-${icon}`} style={{ fontSize: 15, color: "var(--fg)" }} />
        <span style={{ flex: 1 }}>{title}</span>
        {action}
      </div>
      {children}
    </section>
  )
}

const empty = (text: string) => <span className="h-muted" style={{ fontSize: 13 }}>{text}</span>

export function TodayBrief({ onAsk }: { onAsk: (text: string) => void }) {
  const [b, setB] = useState<Brief | null>(null)
  const [failed, setFailed] = useState(false)
  const [city, setCity] = useState("")

  const load = useCallback(async () => {
    try {
      const res = await fetch("/api/today", { cache: "no-store" })
      if (!res.ok) throw new Error(String(res.status))
      setB(await res.json())
    } catch { setFailed(true) }
  }, [])
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch on mount; state is set after the await
    void load()
    // the walkthrough just saved a name / city: show it
    const again = () => void load()
    window.addEventListener("hangul:refresh-today", again)
    return () => window.removeEventListener("hangul:refresh-today", again)
  }, [load])

  const tick = async (id: number) => {
    setB((x) => x && { ...x, todos: x.todos.filter((t) => t.id !== id) })
    await fetch(`/api/lists/items/${id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ done: true }) }).catch(() => null)
  }
  const dismiss = async (id: number) => {
    setB((x) => x && { ...x, reminders: x.reminders.filter((r) => r.id !== id) })
    await fetch(`/api/reminders/${id}/done`, { method: "POST" }).catch(() => null)
  }
  const saveCity = async () => {
    if (!city.trim()) return
    const cur = await fetch("/api/settings", { cache: "no-store" }).then((r) => r.json()).catch(() => null)
    if (!cur) return
    const body = { ...cur, city: city.trim() }
    delete body.tones                            // read-only list the GET adds
    await fetch("/api/settings", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
    setCity("")
    void load()
  }

  if (failed) return null                       // the composer below still works
  if (!b) {
    return <div className="h-muted" style={{ fontSize: 13, padding: 12 }} data-testid="today-loading">Getting your day ready…</div>
  }

  const w = b.weather
  const day = w?.daily?.[0]
  return (
    <div style={{ width: "100%", display: "flex", flexDirection: "column", gap: 14 }} data-testid="today">
      <div>
        <h1 className="h-display" style={{ fontSize: 26, margin: 0 }}>
          {b.greeting}{b.name ? `, ${b.name}` : ""}
        </h1>
        <div className="h-muted" style={{ fontSize: 14, marginTop: 4, display: "flex", columnGap: 14, rowGap: 4, alignItems: "center", flexWrap: "wrap" }}>
          <span>{b.date_label}</span>
          {w ? (
            <span data-testid="today-weather" style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
              <i className={`ti ti-${w.current.icon}`} style={{ fontSize: 15 }} /> {Math.round(w.current.temp)}° {w.current.label.toLowerCase()} in {w.place.split(",")[0]}
              {day?.rain_chance != null && day.rain_chance >= 40 ? <span> · ☔ take an umbrella</span> : null}
            </span>
          ) : !b.city ? (
            <form onSubmit={(e) => { e.preventDefault(); void saveCity() }} style={{ display: "inline-flex", gap: 6, alignItems: "center" }} data-testid="today-city">
              <input className="h-input" value={city} onChange={(e) => setCity(e.target.value)} placeholder="Your city, for weather" aria-label="Your city"
                style={{ height: 28, fontSize: 12, width: 170, padding: "2px 8px" }} />
              <button className="h-btn-ghost" type="submit" style={{ fontSize: 12, padding: "2px 8px" }}>Save</button>
            </form>
          ) : null}
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(210px, 1fr))", gap: 10 }}>
        <Tile icon="calendar-event" title="Next up" testId="today-events">
          {b.events === null
            ? <Link href="/vault" style={{ fontSize: 13, color: "var(--link)" }}>Connect Google Calendar →</Link>
            : b.events.length === 0 ? empty("Nothing else today.")
            : b.events.slice(0, 4).map((e, i) => (
              <div key={i} style={{ display: "flex", gap: 8, fontSize: 13 }}>
                <span className="h-muted" style={{ minWidth: 58, fontVariantNumeric: "tabular-nums" }}>{e.all_day ? "All day" : time(e.start)}</span>
                <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{e.summary}</span>
              </div>
            ))}
        </Tile>

        <Tile icon="checklist" title="Reminders & to-dos" testId="today-tasks"
          action={<Link href="/lists" className="h-muted" style={{ fontSize: 11 }}>All</Link>}>
          {b.reminders.length === 0 && b.todos.length === 0 && empty("All clear. Try “remind me to…”.")}
          {b.reminders.map((r) => (
            <div key={`r${r.id}`} style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 13 }}>
              <i className="ti ti-alarm" style={{ fontSize: 14, color: r.status === "sent" ? "var(--err)" : "var(--muted)" }} />
              <span style={{ flex: 1 }}>{r.text} <span className="h-muted" style={{ fontSize: 11 }}>{time(r.due_at)}</span></span>
              {r.status === "sent" && <button className="h-btn-ghost" style={{ fontSize: 11, padding: "1px 6px" }} onClick={() => void dismiss(r.id)}>Done</button>}
            </div>
          ))}
          {b.todos.map((t) => (
            <label key={`t${t.id}`} style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 13, cursor: "pointer" }}>
              <input type="checkbox" onChange={() => void tick(t.id)} aria-label={`Done: ${t.text}`} data-testid={`today-todo-${t.id}`}
                style={{ width: 15, height: 15, accentColor: "var(--fg)" }} />
              <span style={{ flex: 1 }}>{t.text}</span>
              <span className="h-muted" style={{ fontSize: 11 }}>{t.list_name}</span>
            </label>
          ))}
        </Tile>

        <Tile icon="bell-ringing" title="Needs you" testId="today-needs">
          {b.approvals.length === 0 && !(b.emails && b.emails.length) && empty(b.emails === null ? "Nothing waiting." : "No important mail. Nothing waiting.")}
          {b.approvals.map((a) => (
            <Link key={a.run_id} href={a.conversation_id ? `/chat?c=${a.conversation_id}` : "/chat"} data-testid="today-approval"
              style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 13, color: "var(--fg)", textDecoration: "none" }}>
              <i className="ti ti-hand-stop" style={{ fontSize: 14, color: "var(--warn)" }} />
              <span style={{ flex: 1 }}>{APPROVAL_LABEL[a.tool] ?? "An action"} is waiting for your OK</span>
              <i className="ti ti-chevron-right" style={{ fontSize: 13 }} />
            </Link>
          ))}
          {b.emails && b.emails.length > 0 && (
            <>
              {b.emails.slice(0, 3).map((m) => (
                <div key={m.id} style={{ fontSize: 13, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  <i className="ti ti-mail" style={{ fontSize: 13, marginRight: 6 }} />
                  <b style={{ fontWeight: 500 }}>{sender(m.from)}</b> <span className="h-muted">{m.subject}</span>
                </div>
              ))}
              <button className="h-btn-ghost" style={{ fontSize: 12, alignSelf: "flex-start", padding: "2px 6px" }} data-testid="today-inbox"
                onClick={() => onAsk("Summarise my important unread emails and tell me which need a reply")}>
                Summarise my inbox →
              </button>
            </>
          )}
        </Tile>
      </div>
    </div>
  )
}
