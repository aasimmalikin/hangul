"use client"

import { useState } from "react"
import { BrandSetup, type Suggestion } from "@/components/hangul/BrandSetup"

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
  | { kind: "file"; name: string; format: string; size: number; title?: string }
  | { kind: "chart"; name: string; title?: string; rows: Cell[][] }
  | { kind: "table"; title?: string; rows: Cell[][] }
  | { kind: "upgrade"; feature: string; plan: string; plan_label: string }
  | { kind: "contacts"; people: Array<{ name: string; emails: string[]; phones: string[] }> }
  | { kind: "image"; name: string; prompt: string; size: string; source?: string }
  | { kind: "brand_set"; brand: string; brand_id?: number | null; post_id?: number | null; post_kind?: string; layout?: string; source: string
      files: Array<{ name: string; size: string; width: number; height: number; label: string; slide?: number }> }
  | { kind: "brand_setup"; sentence: string; suggestion: Suggestion }
  | { kind: "places"; query: string; places: Array<{ name: string; address: string; type: string; link: string }> }
  | { kind: "route"; origin: string; destination: string; mode: string; minutes?: number; km?: number; link: string }
  | { kind: "issues"; items: Array<{ repo: string; number: number; title: string; state: string; url: string; pr: boolean; updated: string }> }
  | { kind: "notion_results"; items: Array<{ id: string; title: string; type: string; url: string; edited: string }> }
  | { kind: "slack_messages"; items: Array<{ channel: string; user: string; text: string; link: string }> }
  | { kind: "sales_logged"; business: string; day: string; sales: number; bills: number | null; closed: boolean
      breakeven: number | null; week: { total: number; days: number; change: number | null }; url: string }
  | { kind: "sales_forecast"; business: string; tomorrow: string; url: string
      forecast: { status: string; value?: number | null; low?: number | null; high?: number | null; accuracy?: number | null
                  days_logged?: number; days_needed?: number; reasons?: Array<{ key: string; label: string; effect: number }> } | null
      slow: { slow: boolean; breakeven: number | null } | null; ideas: Array<{ key: string; title: string; discount: number }>
      locked: Array<{ feature: string; plan: string }> }
  | { kind: "business_setup"; id: number; name: string; url: string }
  | { kind: "customers"; title: string; url: string
      items: Array<{ id?: number; customer_id?: number; name: string; phone?: string; birthday?: string | null; date?: string
                     visits?: number; last_visit?: string | null; days_away?: number; in_days?: number; note?: string }> }
  | { kind: "launch_plan"; id: number; title: string; status: string; sourced: boolean; unit: string; startup_total: number
      profit: number; breakeven_per_day: number | null; payback_months: number | null; items: number; url: string
      access: { allowed: boolean; reason: string | null; detail: string; plan_needed: string | null } | null }

type Cell = string | number | null

const KINDS = new Set(["reminder", "reminders", "todo_list", "notes", "weather", "conversion", "world_clock", "webpage",
  "file", "chart", "table", "upgrade", "contacts", "image", "places", "route", "issues", "notion_results", "slack_messages",
  "brand_set", "brand_setup", "launch_plan", "sales_logged", "sales_forecast", "business_setup", "customers"])

const MODE_ICON: Record<string, string> = { car: "car", bike: "bike", foot: "walk" }
const ext = { target: "_blank", rel: "noopener noreferrer nofollow" } as const
const rowLink = { fontSize: 14, color: "var(--link)", textDecoration: "none" } as const

const FILE_ICON: Record<string, string> = {
  pdf: "file-type-pdf", docx: "file-type-doc", pptx: "presentation", xlsx: "file-spreadsheet",
  csv: "file-type-csv", md: "markdown", txt: "file-text",
}
const FILE_LABEL: Record<string, string> = {
  pdf: "PDF", docx: "Word document", pptx: "Slides", xlsx: "Excel spreadsheet", csv: "CSV", md: "Markdown", txt: "Text file",
}
const fileUrl = (name: string) => `/api/files/${encodeURIComponent(name)}`
const fmtSize = (n: number) => (n < 1024 * 1024 ? `${Math.max(1, Math.round(n / 1024))} KB` : `${(n / 1024 / 1024).toFixed(1)} MB`)
const fmtCell = (v: Cell) => (typeof v === "number" ? v.toLocaleString() : v ?? "")

function DataTable({ rows }: { rows: Cell[][] }) {
  const [head, ...body] = rows
  if (!head) return null
  return (
    <div style={{ overflowX: "auto", maxHeight: 320 }}>
      <table style={{ borderCollapse: "collapse", fontSize: 13, width: "100%" }}>
        <thead>
          <tr>{head.map((h, i) => <th key={i} style={{ textAlign: "left", padding: "4px 10px 4px 0", borderBottom: "0.5px solid var(--surface-border)", fontWeight: 500, whiteSpace: "nowrap" }}>{String(h)}</th>)}</tr>
        </thead>
        <tbody>
          {body.map((r, ri) => (
            <tr key={ri}>{r.map((v, ci) => (
              <td key={ci} style={{ padding: "4px 10px 4px 0", borderBottom: "0.5px solid var(--surface-border)",
                textAlign: typeof v === "number" ? "right" : "left", fontVariantNumeric: "tabular-nums", whiteSpace: "nowrap" }}>{fmtCell(v)}</td>
            ))}</tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

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

/** Finished brand images: one tab per size, each downloadable. */
function BrandSet({ ui, onAsk }: { ui: Extract<DailyUi, { kind: "brand_set" }>; onAsk?: (text: string) => void }) {
  const [tab, setTab] = useState(0)
  const f = ui.files[Math.min(tab, ui.files.length - 1)]
  if (!f) return null
  return (
    <Card icon="photo-edit" title={ui.brand ? `Ready to post · ${ui.brand}` : "Ready to post"} testId="card-brand-set">
      {ui.files.length > 1 && (
        <div role="tablist" style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          {ui.files.map((x, i) => (
            <button key={x.name} role="tab" aria-selected={i === tab} className="h-chip" data-testid="brand-set-tab" onClick={() => setTab(i)}
              style={i === tab ? { background: "var(--solid-bg)", color: "var(--solid-fg)", borderColor: "var(--solid-bg)" } : undefined}>
              {x.slide ? `Slide ${x.slide} · ` : ""}{x.label}
            </button>
          ))}
        </div>
      )}
      {/* eslint-disable-next-line @next/next/no-img-element -- a private, per-user file behind the BFF */}
      <img src={fileUrl(f.name)} alt={`${f.label} (${f.width}×${f.height})`}
        style={{ width: "100%", maxHeight: 420, objectFit: "contain", borderRadius: 10, background: "var(--surface-hover)" }} />
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <span className="h-muted" style={{ fontSize: 12, flex: 1 }}>{f.width}×{f.height}</span>
        <a className="h-btn-solid" href={fileUrl(f.name)} download={f.name} data-testid="brand-set-download" style={{ fontSize: 12, textDecoration: "none", gap: 4 }}>
          <i className="ti ti-download" style={{ fontSize: 13 }} /> Download
        </a>
        {ui.post_id && (
          <a className="h-btn-ghost" href={`/api/posts/${ui.post_id}/zip`} data-testid="brand-set-zip" style={{ fontSize: 12, textDecoration: "none", gap: 4 }}>
            <i className="ti ti-file-zip" style={{ fontSize: 13 }} /> Everything
          </a>
        )}
        {onAsk && (
          <button className="h-btn-ghost" style={{ fontSize: 12 }} onClick={() => onAsk(`Make another version of the post from ${ui.source}, with different wording`)}>
            Make another
          </button>
        )}
      </div>
      {ui.post_id && ui.brand_id && (
        <a className="h-chip" href={`/brands/${ui.brand_id}?tab=posts&post=${ui.post_id}`} data-testid="brand-set-studio"
          style={{ alignSelf: "flex-start", textDecoration: "none", color: "var(--fg)" }}>
          <i className="ti ti-message-2" style={{ fontSize: 12, marginRight: 5 }} /> Captions &amp; client review in the Brand Studio
        </a>
      )}
    </Card>
  )
}

export function DailyCard({ ui, onAsk }: { ui: DailyUi; onAsk?: (text: string) => void }) {
  switch (ui.kind) {
    case "brand_set":
      return <BrandSet ui={ui} onAsk={onAsk} />
    case "brand_setup":
      return <div style={{ maxWidth: 560 }}><BrandSetup initialSentence={ui.sentence} initialSuggestion={ui.suggestion} compact /></div>
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
    case "file":
      return (
        <Card icon={FILE_ICON[ui.format] ?? "file"} title={FILE_LABEL[ui.format] ?? "File"} testId="card-file">
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 14, fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{ui.name}</div>
              <div className="h-muted" style={{ fontSize: 12 }}>{fmtSize(ui.size)}</div>
            </div>
            <a className="h-btn-solid" href={fileUrl(ui.name)} download={ui.name} data-testid="file-download" style={{ textDecoration: "none", gap: 6 }}>
              <i className="ti ti-download" style={{ fontSize: 14 }} /> Download
            </a>
          </div>
        </Card>
      )
    case "chart":
      return (
        <Card icon="chart-pie" title={ui.title || "Chart"} testId="card-chart">
          {/* eslint-disable-next-line @next/next/no-img-element -- a private, per-user file behind the BFF */}
          <img src={fileUrl(ui.name)} alt={ui.title || "Chart"} style={{ width: "100%", borderRadius: 8 }} />
          <a href={fileUrl(ui.name)} download={ui.name} className="h-muted" style={{ fontSize: 12 }}>Download chart</a>
        </Card>
      )
    case "table":
      return (
        <Card icon="table" title={ui.title || "Result"} testId="card-table">
          <DataTable rows={ui.rows} />
        </Card>
      )
    case "contacts":
      return (
        <Card icon="address-book" title="Contacts" testId="card-contacts">
          {ui.people.map((p) => (
            <div key={(p.emails[0] ?? p.name) + p.name} style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <span style={{ width: 28, height: 28, borderRadius: "50%", display: "grid", placeItems: "center", fontSize: 13,
                background: "var(--surface-hover)", flexShrink: 0 }}>{(p.name[0] ?? "?").toUpperCase()}</span>
              <div style={{ minWidth: 0 }}>
                <div style={{ fontSize: 14 }}>{p.name}</div>
                <div className="h-muted" style={{ fontSize: 12, overflow: "hidden", textOverflow: "ellipsis" }}>
                  {[...p.emails, ...p.phones].join(" · ")}
                </div>
              </div>
            </div>
          ))}
        </Card>
      )
    case "image":
      return (
        <Card icon="photo" title="Image" testId="card-image">
          {/* eslint-disable-next-line @next/next/no-img-element -- a private, per-user file behind the BFF */}
          <img src={fileUrl(ui.name)} alt={ui.prompt} style={{ width: "100%", borderRadius: 10 }} />
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span className="h-muted" style={{ fontSize: 12, flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={ui.prompt}>{ui.prompt}</span>
            <a className="h-btn-ghost" href={fileUrl(ui.name)} download={ui.name} style={{ fontSize: 12, textDecoration: "none", gap: 4 }}>
              <i className="ti ti-download" style={{ fontSize: 13 }} /> Download
            </a>
          </div>
          {onAsk && (
            <button className="h-chip" data-testid="image-finish" style={{ alignSelf: "flex-start" }}
              onClick={() => onAsk(`Finish ${ui.name} as a post for my brand: add a headline and the logo`)}>
              <i className="ti ti-photo-edit" style={{ fontSize: 12, marginRight: 5 }} /> Finish for my brand
            </button>
          )}
        </Card>
      )
    case "places":
      return (
        <Card icon="map-pin" title={ui.query} testId="card-places">
          {ui.places.map((p, i) => (
            <div key={p.address + i}>
              <a href={p.link} {...ext} style={rowLink}>{p.name}</a>
              {p.type && <span className="h-muted" style={{ fontSize: 11 }}> · {p.type}</span>}
              <div className="h-muted" style={{ fontSize: 12 }}>{p.address}</div>
            </div>
          ))}
          <div className="h-muted" style={{ fontSize: 10 }}>© OpenStreetMap contributors</div>
        </Card>
      )
    case "route":
      return (
        <Card icon={MODE_ICON[ui.mode] ?? "route"} title={`${ui.origin} → ${ui.destination}`} testId="card-route">
          {ui.minutes != null ? (
            <div style={{ fontSize: 15 }}>
              <strong>{ui.minutes < 60 ? `${ui.minutes} min` : `${Math.floor(ui.minutes / 60)} h ${ui.minutes % 60} min`}</strong>
              <span className="h-muted"> · {ui.km} km · no live traffic</span>
            </div>
          ) : (
            <div className="h-muted" style={{ fontSize: 13 }}>Times for this way of travelling are on Google Maps.</div>
          )}
          <a className="h-btn-solid" href={ui.link} {...ext} style={{ textDecoration: "none", alignSelf: "flex-start", gap: 6 }}>
            <i className="ti ti-navigation" style={{ fontSize: 14 }} /> Open directions
          </a>
        </Card>
      )
    case "issues":
      return (
        <Card icon="brand-github" title="GitHub" testId="card-issues">
          {ui.items.map((i) => (
            <div key={i.url} style={{ display: "flex", gap: 8, alignItems: "baseline" }}>
              <i className={`ti ${i.pr ? "ti-git-pull-request" : "ti-circle-dot"}`} style={{ fontSize: 13, color: i.state === "open" ? "var(--ok)" : "var(--muted)" }} />
              <div style={{ minWidth: 0 }}>
                <a href={i.url} {...ext} style={rowLink}>{i.title}</a>
                <div className="h-muted" style={{ fontSize: 11 }}>{i.repo}#{i.number} · updated {i.updated}</div>
              </div>
            </div>
          ))}
        </Card>
      )
    case "notion_results":
      return (
        <Card icon="brand-notion" title="Notion" testId="card-notion">
          {ui.items.map((n) => (
            <div key={n.id}>
              <a href={n.url} {...ext} style={rowLink}>{n.title}</a>
              <span className="h-muted" style={{ fontSize: 11 }}> · edited {n.edited}</span>
            </div>
          ))}
        </Card>
      )
    case "slack_messages":
      return (
        <Card icon="brand-slack" title="Slack" testId="card-slack">
          {ui.items.map((m, i) => (
            <div key={(m.link ?? "") + i} style={{ fontSize: 13 }}>
              <span className="h-muted" style={{ fontSize: 11 }}>#{m.channel} · {m.user}</span>
              <div>{m.link ? <a href={m.link} {...ext} style={{ color: "var(--fg)", textDecoration: "none" }}>{m.text}</a> : m.text}</div>
            </div>
          ))}
        </Card>
      )
    case "sales_logged": {
      // a receipt (direction A): what was logged, for which day, and how it compares; a wrong number is easy to spot
      const rs = (v: number) => `₹${Math.round(v).toLocaleString("en-IN")}`
      const day = new Date(ui.day + "T12:00:00").toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short" })
      return (
        <div className="h-receipt" data-testid="card-sales-logged">
          <div className="h-receipt-head"><span>Logged · {day}</span><span>{ui.business}</span></div>
          <div className="h-receipt-body">
            <div style={{ display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap" }}>
              <span className="h-display" style={{ fontSize: 32, fontWeight: 600, lineHeight: 1.05 }}>{ui.closed ? "Closed" : rs(ui.sales)}</span>
              {ui.bills ? <span style={{ fontSize: 16 }}>{ui.bills} bills</span> : null}
            </div>
            {!ui.closed && ui.breakeven ? (
              <div style={{ fontSize: 15, fontWeight: 600, color: ui.sales >= ui.breakeven ? "var(--up)" : "var(--down)" }}>
                {ui.sales >= ui.breakeven ? "↑" : "↓"} {rs(Math.abs(ui.sales - ui.breakeven))} {ui.sales >= ui.breakeven ? "above" : "below"} break-even
              </div>
            ) : null}
            <div className="h-muted" style={{ fontSize: 14 }}>
              This week: {rs(ui.week.total)}{ui.week.change !== null ? ` (${ui.week.change >= 0 ? "↑" : "↓"} ${Math.abs(Math.round(ui.week.change * 100))}% on last week)` : ""}
            </div>
            <div className="h-muted" style={{ fontSize: 14 }}>Wrong? Just say the right number.</div>
            <a className="h-btn-ghost" href={ui.url} style={{ alignSelf: "flex-start", textDecoration: "none", fontSize: 14, padding: "6px 0" }}>How&apos;s business →</a>
          </div>
        </div>
      )
    }
    case "sales_forecast": {
      const rs = (v?: number | null) => (v === null || v === undefined ? "—" : `₹${Math.round(v).toLocaleString("en-IN")}`)
      const f = ui.forecast
      const weekday = new Date(ui.tomorrow + "T12:00:00").toLocaleDateString("en-IN", { weekday: "long" })
      return (
        <Card icon="trending-up" title={`${ui.business} · tomorrow, ${weekday}`} testId="card-sales-forecast">
          {f?.status === "ready" ? (
            <>
              <div style={{ display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap" }}>
                <span style={{ fontSize: 22, fontWeight: 600 }}>{rs(f.value)}</span>
                <span className="h-muted" style={{ fontSize: 13 }}>likely {rs(f.low)} – {rs(f.high)}</span>
                {ui.slow?.slow && <span className="h-badge" data-tone="warn">Looks slow</span>}
              </div>
              {(f.reasons ?? []).length > 0 && (
                <div className="h-muted" style={{ fontSize: 12 }}>{(f.reasons ?? []).map((r) => `${r.label} ${r.effect > 0 ? "+" : ""}${Math.round(r.effect * 100)}%`).join(" · ")}</div>
              )}
              {ui.ideas.length > 0 && <div style={{ fontSize: 13 }}>Ideas: {ui.ideas.map((i) => i.title).join(", ")}</div>}
            </>
          ) : f?.status === "learning" ? (
            <div style={{ fontSize: 14 }}>Learning: {f.days_logged} of 14 days logged.</div>
          ) : (
            <div style={{ fontSize: 14 }}>Tomorrow&apos;s forecast is part of Plus and Pro.</div>
          )}
          <a className="h-btn-solid" href={ui.url} style={{ alignSelf: "flex-start", textDecoration: "none", fontSize: 13 }} data-testid="sales-card-open">
            {ui.ideas.length ? "See the ideas" : "Open How's business"}
          </a>
        </Card>
      )
    }
    case "business_setup":
      return (
        <Card icon="building-store" title="How's business" testId="card-business-setup">
          <div style={{ fontSize: 14 }}>{ui.name} is set up. Tell Hangul each day&apos;s sales in a sentence.</div>
          <a className="h-btn-ghost" href={ui.url} style={{ alignSelf: "flex-start", textDecoration: "none", fontSize: 13 }}>Open →</a>
        </Card>
      )
    case "customers":
      return (
        <Card icon="users" title={ui.title} testId="card-customers">
          {ui.items.map((c) => (
            <div key={`${c.id ?? c.customer_id ?? c.name}`} style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <span style={{ width: 28, height: 28, borderRadius: "50%", display: "grid", placeItems: "center", fontSize: 13,
                background: "var(--surface-hover)", flexShrink: 0 }}>{(c.name[0] ?? "?").toUpperCase()}</span>
              <div style={{ minWidth: 0 }}>
                <div style={{ fontSize: 14 }}>{c.name}</div>
                <div className="h-muted" style={{ fontSize: 12, overflow: "hidden", textOverflow: "ellipsis" }}>
                  {[c.phone, c.date ? `birthday ${c.date.slice(5)}` : c.birthday ? `birthday ${c.birthday.slice(-5)}` : "",
                    c.days_away ? `away ${c.days_away} days` : c.visits ? `${c.visits} visit${c.visits === 1 ? "" : "s"}` : "", c.note]
                    .filter(Boolean).join(" · ")}
                </div>
              </div>
            </div>
          ))}
          <a className="h-btn-ghost" href={ui.url} style={{ alignSelf: "flex-start", textDecoration: "none", fontSize: 13 }}>All customers →</a>
        </Card>
      )
    case "launch_plan": {
      const rs = (v: number) => `₹${Math.round(v).toLocaleString("en-IN")}`
      const limited = !ui.sourced && ui.access && !ui.access.allowed && ui.access.reason !== "not_asked"
      return (
        <Card icon="rocket" title="Launch plan" testId="card-launch-plan">
          <div style={{ fontSize: 15, fontWeight: 600 }}>{ui.title}</div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 8, fontSize: 13 }}>
            <span><span className="h-muted" style={{ display: "block", fontSize: 11 }}>To start</span>{rs(ui.startup_total)}</span>
            <span><span className="h-muted" style={{ display: "block", fontSize: 11 }}>Break-even</span>{ui.breakeven_per_day ?? "—"} {ui.unit}s/day</span>
            <span><span className="h-muted" style={{ display: "block", fontSize: 11 }}>Pays back</span>{ui.payback_months ? `${ui.payback_months} mo` : "—"}</span>
          </div>
          <div className="h-muted" style={{ fontSize: 12 }}>
            {ui.status === "sourcing" ? `Searching live prices for ${ui.items} items now; the plan fills in by itself.`
              : ui.sourced ? "With live prices." : "Hangul's estimates. Every number can be edited."}
          </div>
          {limited && ui.access && <div className="h-muted" style={{ fontSize: 12 }}>{ui.access.detail}</div>}
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <a className="h-btn-solid" href={ui.url} style={{ textDecoration: "none" }} data-testid="launch-card-open">Open the plan</a>
            {limited && ui.access?.plan_needed && (
              <a className="h-btn-ghost" href={`/billing?upgrade=${encodeURIComponent(ui.access.plan_needed)}`} style={{ textDecoration: "none" }}>
                Get live prices
              </a>
            )}
          </div>
        </Card>
      )
    }
    case "upgrade":
      return (
        <Card icon="lock" title={`${ui.plan_label} feature`} testId="card-upgrade">
          <div style={{ fontSize: 14 }}>{ui.feature} is included with {ui.plan_label}.</div>
          <div>
            <a className="h-btn-solid" href={`/billing?upgrade=${encodeURIComponent(ui.plan)}`} style={{ textDecoration: "none" }}>
              Upgrade to {ui.plan_label}
            </a>
          </div>
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
