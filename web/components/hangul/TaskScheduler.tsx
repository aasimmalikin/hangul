"use client"

import { useEffect, useState } from "react"
import type { ConnectorInfo } from "@/lib/connectors"

/**
 * Settings → Scheduled tasks: make one in three plain steps (what → when → how it
 * reports back) with a sentence saying what will happen, and see each task's next
 * run and state at a glance.
 *
 * The backend stores 24-hour HH:MM plus an optional weekday mask (bit 0 = Monday)
 * or a single date (a one-off); see harness.db.tasks. While it runs, calendar
 * actions and email drafts just happen; sending email and GitHub / Slack / Notion /
 * Docs / Sheets changes wait for an Approve tap, so such a task runs 5 minutes early
 * and asks on WhatsApp (Plus, Pro) or by email (Free) -- harness.preapproval.
 */

export type Task = {
  id: number; title: string; question: string; every_minutes: number | null; daily_at: string | null
  days?: number | null; run_on?: string | null; asks_first?: string[]
  connectors: string[]; mode: string; enabled: boolean; next_run_at: string | null; last_run_at: string | null
  last_status: string; last_run_id: string | null; last_answer: string; deliver_email?: boolean
}

type Preview = { apps: string[]; connected: string[]; title: string; asks_first: string[]; lead_minutes: number }

type Api = <T>(path: string, init?: RequestInit) => Promise<T>

const WEEK_MINUTES = 7 * 24 * 60
const WEEKDAYS = 0b0011111
const DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
const HOURS = Array.from({ length: 12 }, (_, i) => i + 1)
const MINUTES = Array.from({ length: 60 }, (_, i) => i)
const INTERVALS = [15, 30, 60, 120, 180, 240, 360, 720]

type Kind = "once" | "daily" | "weekdays" | "days" | "interval"
const KINDS: { key: Kind; label: string }[] = [
  { key: "once", label: "Once" },
  { key: "daily", label: "Every day" },
  { key: "weekdays", label: "Weekdays" },
  { key: "days", label: "On certain days" },
  { key: "interval", label: "Every few hours" },
]

const IDEAS = [
  "Brief me on today's calendar and important unread email",
  "Find a free 30-minute slot this afternoon and block it as focus time",
  "List PRs waiting for my review and issues assigned to me",
  "Remind me what's on my calendar tomorrow and anything I need to prepare",
]

// ---------------------------------------------------------------- time helpers

/** "16:10" (what the API stores) <-> hour 1-12, minute, AM/PM (what the form shows). */
export function to12(hhmm: string): { hour: number; minute: number; pm: boolean } {
  const [h, m] = hhmm.split(":").map(Number)
  return { hour: h % 12 === 0 ? 12 : h % 12, minute: m || 0, pm: h >= 12 }
}
export function from12(hour: number, minute: number, pm: boolean): string {
  const h = (hour % 12) + (pm ? 12 : 0)
  return `${String(h).padStart(2, "0")}:${String(minute).padStart(2, "0")}`
}
/** "16:10" -> "4:10 PM" */
export function clock12(hhmm: string): string {
  const { hour, minute, pm } = to12(hhmm)
  return `${hour}:${String(minute).padStart(2, "0")} ${pm ? "PM" : "AM"}`
}
const localDate = (d = new Date()) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`
const dateLabel = (ymd: string) => new Date(`${ymd}T12:00:00`).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" })
const every = (m: number) => (m % 60 === 0 ? (m === 60 ? "every hour" : `every ${m / 60} hours`) : `every ${m} min`)

function daysLabel(mask: number): string {
  if (mask === WEEKDAYS) return "weekdays"
  if (mask === 0b1100000) return "weekends"
  if (mask === 0b1111111) return "daily"
  return DAY_NAMES.filter((_, i) => mask >> i & 1).join(", ")
}

/** "daily at 8:00 AM", "weekdays at 9:00 AM", "once on Tue 6 Oct at 5:15 PM", "every 2 hours". */
export function scheduleLabel(t: { every_minutes: number | null; daily_at: string | null; days?: number | null; run_on?: string | null }): string {
  if (t.daily_at && t.run_on) return `once on ${dateLabel(t.run_on)} at ${clock12(t.daily_at)}`
  if (t.daily_at && t.days) {
    const d = daysLabel(t.days)
    return d === "daily" || d === "weekdays" || d === "weekends" ? `${d} at ${clock12(t.daily_at)}`
      : (t.days & (t.days - 1)) === 0 ? `every ${d} at ${clock12(t.daily_at)}` : `${d} at ${clock12(t.daily_at)}`
  }
  if (t.daily_at) return t.every_minutes === WEEK_MINUTES ? `weekly at ${clock12(t.daily_at)}` : `daily at ${clock12(t.daily_at)}`
  return t.every_minutes === WEEK_MINUTES ? "weekly" : every(t.every_minutes ?? 60)
}

/** "Today, 5:15 PM" / "Tomorrow, 9:00 AM" / "Thu 8 Oct, 9:00 AM" */
function friendly(iso: string | null): string {
  if (!iso) return "—"
  const d = new Date(iso)
  const day = localDate(d)
  const today = localDate()
  const tomorrow = localDate(new Date(Date.now() + 86_400_000))
  const time = d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })
  if (day === today) return `Today, ${time}`
  if (day === tomorrow) return `Tomorrow, ${time}`
  return `${d.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" })}, ${time}`
}

const STATUS: Record<string, { text: string; tone: string }> = {
  never: { text: "Not run yet", tone: "var(--muted)" },
  running: { text: "Running…", tone: "var(--link)" },
  done: { text: "Done", tone: "var(--ok)" },
  needs_approval: { text: "Waiting for you", tone: "var(--warn)" },
  expired: { text: "Expired", tone: "var(--muted)" },
  failed: { text: "Failed", tone: "var(--err)" },
  needs_plan: { text: "Needs a plan", tone: "var(--warn)" },
}

// ---------------------------------------------------------------- the time picker

function TimePicker({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const t = to12(value)
  return (
    <span style={{ display: "inline-flex", gap: 4, alignItems: "center" }} aria-label="Time of day" role="group">
      <select className="h-input" style={{ width: "auto" }} value={t.hour} aria-label="Hour"
        onChange={(e) => onChange(from12(Number(e.target.value), t.minute, t.pm))}>
        {HOURS.map((h) => <option key={h} value={h}>{h}</option>)}
      </select>
      <span aria-hidden>:</span>
      <select className="h-input" style={{ width: "auto" }} value={t.minute} aria-label="Minute"
        onChange={(e) => onChange(from12(t.hour, Number(e.target.value), t.pm))}>
        {MINUTES.map((m) => <option key={m} value={m}>{String(m).padStart(2, "0")}</option>)}
      </select>
      <select className="h-input" style={{ width: "auto" }} value={t.pm ? "PM" : "AM"} aria-label="AM or PM"
        onChange={(e) => onChange(from12(t.hour, t.minute, e.target.value === "PM"))}>
        <option value="AM">AM</option>
        <option value="PM">PM</option>
      </select>
    </span>
  )
}

function Step({ n, title, children }: { n: number; title: string; children: React.ReactNode }) {
  return (
    <fieldset style={{ border: 0, padding: 0, margin: 0, display: "flex", flexDirection: "column", gap: 8, minWidth: 0 }}>
      <legend style={{ fontSize: 13, fontWeight: 600, padding: 0, marginBottom: 8, display: "flex", gap: 8, alignItems: "center" }}>
        <span aria-hidden style={{ width: 20, height: 20, borderRadius: 10, background: "var(--brand-soft)", color: "var(--fg)", fontSize: 11, display: "inline-flex", alignItems: "center", justifyContent: "center" }}>{n}</span>
        {title}
      </legend>
      {children}
    </fieldset>
  )
}

// ---------------------------------------------------------------- the scheduler

export function TaskScheduler({ tasks, connectors, busy, run, api }: {
  tasks: Task[]; connectors: ConnectorInfo[]; busy: boolean
  run: (fn: () => Promise<unknown>) => Promise<void>; api: Api
}) {
  const [question, setQuestion] = useState("")
  const [title, setTitle] = useState("")
  const [kind, setKind] = useState<Kind>("daily")
  const [time, setTime] = useState("08:00")
  const [date, setDate] = useState(localDate())
  const [days, setDays] = useState(1)                 // Monday
  const [interval, setInterval_] = useState(60)
  const [picked, setPicked] = useState<string[]>([])     // apps ticked by hand
  const [dropped, setDropped] = useState<string[]>([])   // detected apps the user unticked
  const [research, setResearch] = useState(false)
  const [sendMe, setSendMe] = useState(false)
  const [preview, setPreview] = useState<Preview | null>(null)
  const [formError, setFormError] = useState<string | null>(null)

  // what the question will switch on, as you type (the same router a chat uses)
  useEffect(() => {
    const q = question.trim()
    const timer = setTimeout(() => {
      api<Preview>("tasks/preview", { method: "POST", body: JSON.stringify({ question: q }) })
        .then(setPreview).catch(() => setPreview(null))
    }, q ? 500 : 0)
    return () => clearTimeout(timer)
  }, [question, api])

  const detected = (preview?.apps ?? []).filter((k) => !dropped.includes(k))
  const apps = Array.from(new Set([...picked, ...detected]))
  const labelOf = (k: string) => connectors.find((c) => c.key === k)?.label ?? k
  // decided by the server from the apps and the words ("send Priya…" asks; "summarise my email" doesn't)
  const asking = (preview?.asks_first ?? []).filter((k) => apps.includes(k))
  const asksLabel = (k: string) => (k === "gmail" ? "Sending email" : `${labelOf(k)} changes`)
  const asksVerb = asking.length === 1 && asking[0] === "gmail" ? "needs" : "need"
  const leadMin = preview?.lead_minutes ?? 5

  // "has that time passed?" needs a clock; ticked every 30 s rather than read in render
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 30_000)
    return () => clearInterval(id)
  }, [])
  const past = kind === "once" && !(new Date(`${date}T${time}:00`).getTime() > now)

  const summary = (() => {
    const when = kind === "once" ? `On ${dateLabel(date)} at ${clock12(time)}`
      : kind === "daily" ? `Every day at ${clock12(time)}`
      : kind === "weekdays" ? `Every weekday at ${clock12(time)}`
      : kind === "days" ? `Every ${daysLabel(days) === "daily" ? "day" : daysLabel(days)} at ${clock12(time)}`
      : `${every(interval)[0].toUpperCase()}${every(interval).slice(1)}`
    const parts = [`${when}, Hangul will: “${question.trim() || "…"}”`]
    if (apps.length) parts.push(`Using ${apps.map(labelOf).join(", ")}.`)
    if (asking.length) parts.push(`${asking.map(asksLabel).join(" and ")} ${asksVerb} your OK: you'll get an approval ${leadMin} minutes before (WhatsApp, or email on Free).`)
    if (sendMe) parts.push("You'll get the result by email and notification.")
    return parts.join(" ")
  })()

  const reset = () => { setQuestion(""); setTitle(""); setPicked([]); setDropped([]); setResearch(false); setSendMe(false) }

  const add = () => {
    setFormError(null)
    if (past) { setFormError("That time has already passed — pick a later one."); return }
    if (kind === "days" && !days) { setFormError("Pick at least one day."); return }
    const schedule = kind === "once" ? { daily_at: time, run_on: date }
      : kind === "daily" ? { daily_at: time }
      : kind === "weekdays" ? { daily_at: time, days: WEEKDAYS }
      : kind === "days" ? (days === 0b1111111 ? { daily_at: time } : { daily_at: time, days })
      : { every_minutes: interval }
    void run(async () => {
      await api("tasks", {
        method: "POST",
        body: JSON.stringify({
          title: title.trim(), question, connectors: apps, mode: research ? "research" : "default",
          deliver_email: sendMe, ...schedule,
        }),
      })
      reset()
    })
  }

  const toggleApp = (key: string, on: boolean) => {
    if (on) { setPicked((ks) => [...ks, key]); setDropped((ks) => ks.filter((k) => k !== key)) }
    else { setPicked((ks) => ks.filter((k) => k !== key)); if (preview?.apps.includes(key)) setDropped((ks) => [...ks, key]) }
  }

  return (
    <>
      <form onSubmit={(e) => { e.preventDefault(); add() }} data-testid="task-form"
        style={{ display: "flex", flexDirection: "column", gap: 18, border: "0.5px solid var(--surface-border)", borderRadius: 14, padding: 16 }}>
        <Step n={1} title="What should Hangul do?">
          <textarea className="h-input" rows={3} value={question} onChange={(e) => setQuestion(e.target.value)} maxLength={4000} required
            placeholder="In your own words, e.g. “Find a free slot this afternoon and block it as focus time”"
            aria-label="Task question" style={{ resize: "vertical" }} />
          {!question && (
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }} aria-label="Ideas">
              {IDEAS.map((idea) => (
                <button key={idea} type="button" className="h-chip" onClick={() => setQuestion(idea)}>{idea}</button>
              ))}
            </div>
          )}
          {connectors.length > 0 && (
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center", fontSize: 12 }} data-testid="task-apps">
              <span className="h-muted">Apps:</span>
              {connectors.map((c) => (
                <label key={c.key} style={{ display: "flex", gap: 5, alignItems: "center" }}>
                  <input type="checkbox" checked={apps.includes(c.key)} onChange={(e) => toggleApp(c.key, e.target.checked)} /> {c.label}
                  {detected.includes(c.key) && <span className="h-muted" style={{ fontSize: 10 }}>(from your words)</span>}
                </label>
              ))}
            </div>
          )}
        </Step>

        <Step n={2} title="When?">
          <div role="radiogroup" aria-label="How often" style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            {KINDS.map((k) => (
              <button key={k.key} type="button" role="radio" aria-checked={kind === k.key}
                className="h-chip" onClick={() => setKind(k.key)} data-testid={`when-${k.key}`}>{k.label}</button>
            ))}
          </div>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center" }}>
            {kind === "once" && (
              <input className="h-input" type="date" value={date} min={localDate()} onChange={(e) => setDate(e.target.value)}
                aria-label="Date" style={{ width: "auto" }} />
            )}
            {kind === "days" && (
              <div role="group" aria-label="Days" style={{ display: "flex", gap: 4 }}>
                {DAY_NAMES.map((d, i) => (
                  <button key={d} type="button" className="h-chip" aria-pressed={Boolean(days >> i & 1)} aria-label={d}
                    style={{ padding: "6px 10px" }} onClick={() => setDays((m) => m ^ (1 << i))}>{d[0]}</button>
                ))}
              </div>
            )}
            {kind === "interval" ? (
              <select className="h-input" style={{ width: "auto" }} value={interval} onChange={(e) => setInterval_(Number(e.target.value))} aria-label="How often">
                {INTERVALS.map((m) => <option key={m} value={m}>{every(m)}</option>)}
              </select>
            ) : (
              <><span className="h-muted" style={{ fontSize: 13 }}>at</span><TimePicker value={time} onChange={setTime} /></>
            )}
          </div>
          {past && <span style={{ color: "var(--err)", fontSize: 12 }}>That time has already passed.</span>}
        </Step>

        <Step n={3} title="How should it work?">
          <label style={{ display: "flex", gap: 8, alignItems: "flex-start", fontSize: 13 }}>
            <input type="checkbox" checked={sendMe} onChange={(e) => setSendMe(e.target.checked)} aria-label="Email me the result" />
            <span>Send me the result <span className="h-muted">— by email and phone notification</span></span>
          </label>
          <p className="h-muted" style={{ margin: 0, fontSize: 12 }} data-testid="task-rule">
            Calendar events and email drafts just happen.
            {asking.length > 0
              ? <> <b>{asking.map(asksLabel).join(" and ")}</b> {asksVerb} your OK, so this task starts {leadMin} minutes early and asks you on WhatsApp (by email on the Free plan); it goes ahead as soon as you tap Approve.</>
              : <> Sending email, or changes in GitHub, Slack, Notion, Docs and Sheets, need your OK: you&apos;d be asked {leadMin} minutes before, on WhatsApp (by email on the Free plan).</>}
          </p>
          <label style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 13 }}>
            <input type="checkbox" checked={research} onChange={(e) => setResearch(e.target.checked)} /> Deep research <span className="h-muted">(slower, cites sources)</span>
          </label>
          <input className="h-input" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={120} aria-label="Task title"
            placeholder={preview?.title ? `Name (optional) — “${preview.title}”` : "Name (optional)"} />
        </Step>

        <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap", borderTop: "0.5px solid var(--surface-border)", paddingTop: 12 }}>
          <p style={{ margin: 0, flex: "1 1 260px", fontSize: 13 }} data-testid="task-summary">{summary}</p>
          <button className="h-btn-solid" type="submit" disabled={busy || !question.trim() || past}>Add task</button>
        </div>
        {formError && <p role="alert" style={{ margin: 0, color: "var(--err)", fontSize: 12 }}>{formError}</p>}
      </form>

      {tasks.length === 0 ? <p className="h-muted" style={{ fontSize: 13, margin: 0 }}>No scheduled tasks yet.</p> : (
        <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "flex", flexDirection: "column", gap: 10 }}>
          {tasks.map((t) => {
            const st = STATUS[t.last_status] ?? { text: t.last_status, tone: "var(--muted)" }
            return (
              <li key={t.id} style={{ border: "0.5px solid var(--surface-border)", borderRadius: 12, padding: "12px 14px", fontSize: 13 }} data-testid={`task-${t.id}`}>
                <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
                  <strong style={{ fontSize: 14 }}>{t.title}</strong>
                  <span style={{ fontSize: 11, color: st.tone, border: `0.5px solid ${st.tone}`, borderRadius: 10, padding: "1px 8px" }}>{st.text}</span>
                  <span className="h-muted" style={{ fontSize: 12, marginLeft: "auto" }}>
                    {t.enabled ? `Next: ${friendly(t.next_run_at)}` : t.run_on && t.last_run_at ? "finished" : "paused"}
                  </span>
                </div>
                <div className="h-muted" style={{ fontSize: 12, marginTop: 4 }}>
                  {scheduleLabel(t)}{t.connectors.length ? ` · ${t.connectors.join(", ")}` : ""}{t.mode === "research" ? " · research" : ""}{t.deliver_email ? " · emailed" : ""}
                </div>
                <div style={{ fontSize: 12, marginTop: 4 }}>“{t.question}”</div>
                {(t.asks_first ?? []).length > 0 && (
                  <div className="h-muted" style={{ fontSize: 12, marginTop: 4 }}>
                    Asks you 5 minutes before — {(t.asks_first ?? []).map(asksLabel).join(", ").toLowerCase()} — on WhatsApp (email on Free).
                  </div>
                )}
                {t.last_answer && (
                  <details style={{ fontSize: 12, marginTop: 6 }} open={t.last_answer.length <= 160}>
                    <summary className="h-muted" style={{ cursor: "pointer" }}>Last result</summary>
                    <div style={{ whiteSpace: "pre-wrap", marginTop: 4 }}>{t.last_answer.slice(0, 800)}{t.last_answer.length > 800 ? "…" : ""}</div>
                  </details>
                )}
                {t.last_status === "needs_approval" && t.last_run_id && (
                  <div className="h-surface" style={{ padding: "8px 10px", marginTop: 8, fontSize: 12, display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }} data-testid={`task-${t.id}-approval`}>
                    <i className="ti ti-hand-stop" />
                    <span style={{ flex: 1 }}>This run wants to do something that needs your approval.</span>
                    <button className="h-btn-solid" disabled={busy} onClick={() => run(() => api("approve", { method: "POST", body: JSON.stringify({ approval_id: t.last_run_id, decision: "approve" }) }))}>Approve</button>
                    <button className="h-btn-outline" disabled={busy} onClick={() => run(() => api("approve", { method: "POST", body: JSON.stringify({ approval_id: t.last_run_id, decision: "reject" }) }))}>Reject</button>
                  </div>
                )}
                <div style={{ display: "flex", gap: 6, marginTop: 8 }}>
                  <button className="h-btn-ghost" disabled={busy} onClick={() => run(() => api(`tasks/${t.id}/run`, { method: "POST" }))}>Run now</button>
                  {!(t.run_on && !t.enabled && t.last_run_at) && (
                    <button className="h-btn-ghost" disabled={busy} onClick={() => run(() => api(`tasks/${t.id}`, { method: "POST", body: JSON.stringify({ enabled: !t.enabled }) }))}>{t.enabled ? "Pause" : "Resume"}</button>
                  )}
                  <button className="h-btn-ghost" disabled={busy} onClick={() => run(() => api(`tasks/${t.id}`, { method: "DELETE" }))}>Delete</button>
                </div>
              </li>
            )
          })}
        </ul>
      )}
    </>
  )
}
