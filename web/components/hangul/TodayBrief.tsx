"use client"

import Link from "next/link"
import { useCallback, useEffect, useState } from "react"
import { LivingStag, type Suggestion } from "@/components/hangul/LivingStag"
import { TodayTalk } from "@/components/hangul/TodayTalk"

/**
 * The Today screen: what the user needs to know right now, before they ask.
 * Built from GET /api/today (weather for their city, the rest of today's
 * calendar, reminders and to-dos, approvals waiting on them, important
 * unread mail, when to leave for the next event with a place, birthdays this
 * week, replies the user owes, and after 6 pm tomorrow). Every card is one tap from acting: tick a
 * to-do, dismiss a reminder, open the chat that's waiting, ask about the
 * inbox, get directions, or draft birthday wishes. Cards with nothing to say
 * aren't drawn.
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
  // after 6 pm: tomorrow's events (null = Calendar not connected) and reminders
  tomorrow?: { date_label: string; events: Event[] | null; reminders: Array<{ id: number; text: string; due_at: string }> } | null
  // the next event with a place; needs_home = no home address set yet
  leave_by?: { summary: string; start: string; location: string; needs_home?: boolean; minutes?: number | null;
    leave_at?: string; late?: boolean; link?: string } | null
  birthdays?: Array<{ name: string; date: string; in_days: number; turns?: number }> | null
  // people who wrote to the user directly and are still waiting (a day or more); null = Gmail not connected
  replies?: Array<{ thread_id: string; from: string; subject: string; waiting_days: number; unread?: boolean }> | null
  // what tapping the stag offers: the user's usual request at this hour (src/harness/habits.py)
  suggestion?: Suggestion | null
  // the morning check-in (db/checkins.py) and one remembered thing for "You told me…"
  checkin?: { mood: string | null; reply: string | null; streak: number; week: boolean[] } | null
  memory?: { id: number; content: string; kind?: string } | null
  // the quick brief (?quick=1): calendar, mail, weather etc. are still loading
  partial?: boolean
  // the full brief failed: only the quick part is shown
  incomplete?: boolean
}

const time = (iso: string) => {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })
}
const whenDay = (b: { date: string; in_days: number }) =>
  b.in_days === 0 ? "Today" : b.in_days === 1 ? "Tomorrow"
    : new Date(`${b.date}T12:00:00`).toLocaleDateString(undefined, { weekday: "long" })
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

  // Two requests: the quick brief (greeting, reminders, to-dos, approvals; from the database,
  // in milliseconds) is drawn at once, and the full one (calendar, mail, weather, replies owed,
  // birthdays, leave-by; seconds) replaces it. Whichever fails, the other still shows.
  const load = useCallback(async () => {
    const get = async (url: string) => {
      const res = await fetch(url, { cache: "no-store" })
      if (!res.ok) throw new Error(String(res.status))
      return (await res.json()) as Brief
    }
    let full = false, gotQuick = false
    // a refresh keeps the full brief already on screen until the new one arrives
    const quick = get("/api/today?quick=1")
      .then((q) => { gotQuick = true; if (!full) setB((cur) => (cur && !cur.partial ? cur : q)) })
      .catch(() => null)
    try {
      const brief = await get("/api/today")
      full = true
      setB(brief)
    } catch {
      await quick
      if (gotQuick) setB((cur) => cur && { ...cur, partial: false, incomplete: true })   // stop waiting: show what we have
      else setFailed(true)
    }
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
      {/* Hearth: the living stag above the greeting; tap it for what you usually ask at this hour */}
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", textAlign: "center", gap: 4 }}>
        <LivingStag size={118} suggestion={b.suggestion} onAsk={onAsk} />
        <h1 className="h-display" style={{ fontSize: 34, fontWeight: 400, margin: "6px 0 0", lineHeight: 1.1 }}>
          {b.greeting}{b.name ? `, ${b.name}` : ""}.
        </h1>
        <div className="h-muted" style={{ fontSize: 14, marginTop: 4, display: "flex", columnGap: 14, rowGap: 4, alignItems: "center", justifyContent: "center", flexWrap: "wrap" }}>
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

      {/* Hangul talks first: a few short messages with one-tap replies; the cards below keep the detail */}
      {/* Hangul's messages are typed once per day, so they wait for the full brief (the dots meanwhile) */}
      {b.partial
        ? <div className="h-talk" data-testid="today-talk-loading"><div className="h-talk-typing" aria-label="Hangul is getting your day"><i /><i /><i /></div></div>
        : <TodayTalk brief={b} onAsk={onAsk} />}

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(210px, 1fr))", gap: 10 }}>
        {b.leave_by && (
          <Tile icon="car" title={b.leave_by.needs_home || b.leave_by.minutes == null ? "Coming up" : "Leave by"} testId="today-leave">
            {b.leave_by.minutes != null && b.leave_by.leave_at && (
              <div style={{ fontSize: 20, fontWeight: 500, lineHeight: 1.1 }} data-testid="today-leave-time">
                {b.leave_by.late ? "Leave now" : time(b.leave_by.leave_at)}
              </div>
            )}
            <div style={{ fontSize: 13 }}>
              <b style={{ fontWeight: 500 }}>{b.leave_by.summary}</b> at {time(b.leave_by.start)}
              <div className="h-muted" style={{ fontSize: 12, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {b.leave_by.location}{b.leave_by.minutes != null ? ` · ${b.leave_by.minutes} min drive, no live traffic` : ""}
              </div>
            </div>
            {b.leave_by.needs_home ? (
              <Link href="/settings#home" style={{ fontSize: 12, color: "var(--link)" }} data-testid="today-leave-home">
                Add your home address to see when to leave →
              </Link>
            ) : b.leave_by.link ? (
              <a href={b.leave_by.link} target="_blank" rel="noreferrer" style={{ fontSize: 12, color: "var(--link)" }}>Directions →</a>
            ) : null}
          </Tile>
        )}

        <Tile icon="calendar-event" title="Next up" testId="today-events">
          {b.events === null && b.partial
            ? empty("Checking your calendar…")
            : b.events === null && b.incomplete
            ? empty("Couldn't reach your calendar just now.")
            : b.events === null
            ? <Link href="/vault" style={{ fontSize: 13, color: "var(--link)" }}>Connect Google Calendar →</Link>
            : b.events.length === 0 ? empty("Nothing else today.")
            : b.events.slice(0, 4).map((e, i) => (
              <div key={i} style={{ display: "flex", gap: 8, fontSize: 13 }}>
                <span className="h-muted" style={{ minWidth: 58, fontVariantNumeric: "tabular-nums" }}>{e.all_day ? "All day" : time(e.start)}</span>
                <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{e.summary}</span>
              </div>
            ))}
        </Tile>

        {b.tomorrow && ((b.tomorrow.events?.length ?? 0) > 0 || b.tomorrow.reminders.length > 0) && (
          <Tile icon="moon" title={`Tomorrow · ${b.tomorrow.date_label}`} testId="today-tomorrow">
            {(b.tomorrow.events ?? []).slice(0, 4).map((e, i) => (
              <div key={`e${i}`} style={{ display: "flex", gap: 8, fontSize: 13 }}>
                <span className="h-muted" style={{ minWidth: 58, fontVariantNumeric: "tabular-nums" }}>{e.all_day ? "All day" : time(e.start)}</span>
                <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{e.summary}</span>
              </div>
            ))}
            {b.tomorrow.reminders.slice(0, 4).map((r) => (
              <div key={`r${r.id}`} style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 13 }}>
                <i className="ti ti-alarm h-muted" style={{ fontSize: 14, minWidth: 58 }} />
                <span style={{ flex: 1 }}>{r.text} <span className="h-muted" style={{ fontSize: 11 }}>{time(r.due_at)}</span></span>
              </div>
            ))}
          </Tile>
        )}

        <Tile icon="checklist" title="Reminders & to-dos" testId="today-tasks"
          action={<Link href="/kept" className="h-muted" style={{ fontSize: 11 }}>All</Link>}>
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

        {b.replies && b.replies.length > 0 && (
          <Tile icon="mail-forward" title={`Replies you owe · ${b.replies.length}`} testId="today-replies">
            {b.replies.slice(0, 3).map((r) => (
              <a key={r.thread_id} href={`https://mail.google.com/mail/u/0/#inbox/${r.thread_id}`} target="_blank" rel="noreferrer"
                data-testid="today-reply"
                style={{ display: "flex", gap: 8, alignItems: "baseline", fontSize: 13, color: "var(--fg)", textDecoration: "none", minWidth: 0 }}>
                <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  <b style={{ fontWeight: 500 }}>{sender(r.from)}</b> <span className="h-muted">{r.subject}</span>
                </span>
                <span className="h-muted" style={{ fontSize: 11, whiteSpace: "nowrap" }}>
                  {r.waiting_days <= 1 ? "1 day" : `${r.waiting_days} days`}
                </span>
              </a>
            ))}
            <button className="h-btn-ghost" style={{ fontSize: 12, alignSelf: "flex-start", padding: "2px 6px" }} data-testid="today-draft-replies"
              onClick={() => onAsk("Draft short replies to the emails I owe a reply to, starting with the one waiting longest.")}>
              Draft replies →
            </button>
          </Tile>
        )}

        {b.birthdays && b.birthdays.length > 0 && (
          <Tile icon="cake" title="Birthdays" testId="today-birthdays">
            {b.birthdays.slice(0, 4).map((p) => (
              <div key={`${p.name}${p.date}`} style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 13 }}>
                <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  <b style={{ fontWeight: 500 }}>{p.name}</b> <span className="h-muted">{whenDay(p)}{p.turns ? ` · turns ${p.turns}` : ""}</span>
                </span>
                <button className="h-btn-ghost" style={{ fontSize: 11, padding: "1px 6px" }} data-testid="today-birthday-wish"
                  onClick={() => onAsk(`Draft a short, warm birthday message for ${p.name}${p.in_days === 0 ? " (it's today)" : ` for ${whenDay(p)}`}.`)}>
                  Wish
                </button>
              </div>
            ))}
          </Tile>
        )}

        {/* only when something actually needs the user: a recent approval or important unread mail */}
        {(b.approvals.length > 0 || (b.emails?.length ?? 0) > 0) && (
        <Tile icon="bell-ringing" title="Needs you" testId="today-needs">
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
                onClick={() => onAsk("Summarise my important unread emails from other people (not ones I sent myself or Hangul's own emails to me) and tell me which need a reply")}>
                Summarise my inbox →
              </button>
            </>
          )}
        </Tile>
        )}
      </div>
    </div>
  )
}
