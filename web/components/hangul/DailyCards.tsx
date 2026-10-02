"use client"

import { useState } from "react"

/**
 * Cards for the everyday-assistant tools (backend `tools/builtin/daily.py`):
 * reminders, lists, notes, weather, conversions, world clock and link
 * previews. Each tool attaches a `ui` block to its result; these render it in
 * the thread right after the step, in the app's own `.h-*` / `var(--…)` theme.
 * The checklist is live: ticking an item calls `/api/lists/items/<id>`.
 */

type TodoItem = { id: number; list_name: string; text: string; done: boolean }
type Reminder = { id: number; text: string; due_at: string; status: string; local?: string }
type NoteRow = { id: number; text: string; created_at: string }
type Day = { date: string; label: string; icon: string; max: number; min: number; rain_chance: number | null }

export type DailyUi =
  | { kind: "reminder"; reminder: Reminder; local: string; tz: string }
  | { kind: "reminders"; reminders: Reminder[]; tz: string }
  | { kind: "todo_list"; list: string | null; items: TodoItem[] }
  | { kind: "notes"; notes: NoteRow[]; saved?: boolean }
  | { kind: "weather"; place: string; current: { temp: number; feels: number; humidity: number; wind: number; label: string; icon: string }; daily: Day[] }
  | { kind: "conversion"; from: string; to: string; note?: string }
  | { kind: "world_clock"; rows: Array<{ place: string; zone: string; time: string; day: string }>; home: string; at: string | null }
  | { kind: "webpage"; url: string; title: string; host: string; excerpt: string }

const KINDS = new Set(["reminder", "reminders", "todo_list", "notes", "weather", "conversion", "world_clock", "webpage"])

export function isDailyUi(v: unknown): v is DailyUi {
  return Boolean(v && typeof v === "object" && KINDS.has(String((v as { kind?: unknown }).kind)))
}

function Card({ icon, title, children, testId }: { icon: string; title: string; children: React.ReactNode; testId: string }) {
  return (
    <div className="h-surface" data-testid={testId}
      style={{ padding: "12px 14px", borderRadius: 14, display: "flex", flexDirection: "column", gap: 8, maxWidth: 520 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12 }} className="h-muted">
        <i className={`ti ti-${icon}`} style={{ fontSize: 15, color: "var(--fg)" }} />
        <span>{title}</span>
      </div>
      {children}
    </div>
  )
}

const dayName = (iso: string) => {
  const d = new Date(iso + "T12:00:00")
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString(undefined, { weekday: "short" })
}

function Checklist({ ui }: { ui: Extract<DailyUi, { kind: "todo_list" }> }) {
  const [items, setItems] = useState(ui.items)
  const [error, setError] = useState<string | null>(null)
  const toggle = async (it: TodoItem) => {
    const next = !it.done
    setItems((xs) => xs.map((x) => (x.id === it.id ? { ...x, done: next } : x)))
    const res = await fetch(`/api/lists/items/${it.id}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ done: next }),
    }).catch(() => null)
    if (!res?.ok) {
      setItems((xs) => xs.map((x) => (x.id === it.id ? { ...x, done: !next } : x)))
      setError("Couldn't save that — try again.")
    } else setError(null)
  }
  const title = ui.list ?? "Your lists"
  return (
    <Card icon="checklist" title={title} testId="card-todo">
      {items.length === 0 && <span className="h-muted" style={{ fontSize: 13 }}>Nothing on this list.</span>}
      {items.map((it) => (
        <label key={it.id} style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 14, cursor: "pointer" }}>
          <input type="checkbox" checked={it.done} onChange={() => void toggle(it)} data-testid={`todo-${it.id}`}
            style={{ width: 16, height: 16, accentColor: "var(--fg)" }} />
          <span style={{ textDecoration: it.done ? "line-through" : undefined, color: it.done ? "var(--muted)" : "var(--fg)" }}>
            {it.text}
          </span>
          {!ui.list && <span className="h-muted" style={{ fontSize: 11, marginLeft: "auto" }}>{it.list_name}</span>}
        </label>
      ))}
      {error && <span style={{ fontSize: 12, color: "var(--err)" }}>{error}</span>}
    </Card>
  )
}

export function DailyCard({ ui }: { ui: DailyUi }) {
  switch (ui.kind) {
    case "reminder":
      return (
        <Card icon="alarm" title="Reminder set" testId="card-reminder">
          <div style={{ fontSize: 15 }}>{ui.reminder.text}</div>
          <div className="h-muted" style={{ fontSize: 12 }}>{ui.local} · you&apos;ll get a notification and an email</div>
        </Card>
      )
    case "reminders":
      return (
        <Card icon="alarm" title="Upcoming reminders" testId="card-reminders">
          {ui.reminders.map((r) => (
            <div key={r.id} style={{ display: "flex", gap: 10, fontSize: 14 }}>
              <span className="h-muted" style={{ minWidth: 130, fontSize: 12, paddingTop: 2 }}>{r.local}</span>
              <span>{r.text}</span>
            </div>
          ))}
        </Card>
      )
    case "todo_list":
      return <Checklist ui={ui} />
    case "notes":
      return (
        <Card icon="notes" title={ui.saved ? "Note saved" : "Your notes"} testId="card-notes">
          {ui.notes.map((n) => (
            <div key={n.id} style={{ fontSize: 14, whiteSpace: "pre-wrap" }}>
              {n.text}
              <div className="h-muted" style={{ fontSize: 11 }}>{new Date(n.created_at).toLocaleDateString()}</div>
            </div>
          ))}
        </Card>
      )
    case "weather":
      return (
        <Card icon={ui.current.icon} title={ui.place} testId="card-weather">
          <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
            <span style={{ fontSize: 32, fontWeight: 500 }}>{Math.round(ui.current.temp)}°</span>
            <span style={{ fontSize: 14 }}>{ui.current.label}</span>
            <span className="h-muted" style={{ fontSize: 12, marginLeft: "auto" }}>
              Feels {Math.round(ui.current.feels)}° · {ui.current.humidity}% · {Math.round(ui.current.wind)} km/h
            </span>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: `repeat(${Math.max(1, ui.daily.length)}, 1fr)`, gap: 6 }}>
            {ui.daily.map((d) => (
              <div key={d.date} style={{ textAlign: "center", fontSize: 12, padding: "6px 0", borderRadius: 10, background: "var(--surface-hover)" }}>
                <div className="h-muted">{dayName(d.date)}</div>
                <i className={`ti ti-${d.icon}`} style={{ fontSize: 18 }} title={d.label} />
                <div>{Math.round(d.max)}° <span className="h-muted">{Math.round(d.min)}°</span></div>
                {d.rain_chance != null && <div className="h-muted" style={{ fontSize: 11 }}>☔ {d.rain_chance}%</div>}
              </div>
            ))}
          </div>
        </Card>
      )
    case "conversion":
      return (
        <Card icon="arrows-exchange" title="Conversion" testId="card-conversion">
          <div style={{ fontSize: 15 }}>{ui.from} = <strong>{ui.to}</strong></div>
          {ui.note && <div className="h-muted" style={{ fontSize: 11 }}>{ui.note}</div>}
        </Card>
      )
    case "world_clock":
      return (
        <Card icon="world" title={ui.at ? `At your ${ui.at.slice(11, 16)}` : "Right now"} testId="card-clock">
          {ui.rows.map((r) => (
            <div key={r.zone + r.place} style={{ display: "flex", justifyContent: "space-between", fontSize: 14 }}>
              <span>{r.place}</span>
              <span><strong>{r.time}</strong> <span className="h-muted" style={{ fontSize: 12 }}>{r.day}</span></span>
            </div>
          ))}
        </Card>
      )
    case "webpage":
      return (
        <Card icon="link" title={ui.host} testId="card-webpage">
          <a href={ui.url} target="_blank" rel="noopener noreferrer nofollow" style={{ fontSize: 14, color: "var(--link)", fontWeight: 500 }}>
            {ui.title}
          </a>
          <div className="h-muted" style={{ fontSize: 12 }}>{ui.excerpt}{ui.excerpt.length >= 280 ? "…" : ""}</div>
        </Card>
      )
  }
}
