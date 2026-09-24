"use client"

import { useState } from "react"

/**
 * Google-styled result panels for the Workspace connector. The agent's tools
 * attach a structured `ui` block to their result; these components render it
 * the way the person knows it from Gmail / Calendar / Drive / Docs, so the
 * result feels like the real product rather than a text dump. Colours are the
 * `--g-*` tokens in globals.css (Google's palette, with a dark variant).
 */

export type GmailMessage = { id: string; thread_id?: string; from: string; to?: string; subject: string; date: string; snippet?: string; labels?: string[]; unread?: boolean; body?: string }
export type GoogleUi =
  | { kind: "gmail_messages"; query?: string; messages: GmailMessage[] }
  | { kind: "gmail_thread"; thread_id?: string; subject?: string; messages: GmailMessage[] }
  | { kind: "gmail_draft"; draft_id?: string; to: string; cc?: string | null; subject: string; body: string }
  | { kind: "gmail_sent"; message_id?: string; draft_id?: string; to?: string; cc?: string | null; subject?: string; body?: string }
  | { kind: "calendar_events"; created?: boolean; time_min?: string; time_max?: string; events: Array<{ id?: string; summary: string; start: string; end: string; all_day?: boolean; location?: string | null; attendees?: string[]; link?: string | null; description?: string }> }
  | { kind: "drive_files"; files: Array<{ id: string; name: string; mime?: string | null; modified?: string | null; size?: string | null; link?: string | null }> }
  | { kind: "docs_document"; id: string; title?: string; text: string }

const AVATAR = ["#1a73e8", "#d93025", "#188038", "#f9ab00", "#9334e6", "#e8710a", "#007b83", "#c5221f"]

function senderName(from: string): string {
  const m = from.match(/^\s*"?([^"<]*?)"?\s*<[^>]+>\s*$/)
  return (m ? m[1] : from.replace(/@.*/, "")).trim() || from
}
function initial(from: string) { return (senderName(from)[0] ?? "?").toUpperCase() }
function avatarColor(s: string) { let h = 0; for (const ch of s) h = (h * 31 + ch.charCodeAt(0)) >>> 0; return AVATAR[h % AVATAR.length] }
function shortDate(s: string): string {
  const d = new Date(s)
  if (Number.isNaN(d.getTime())) return s
  const today = new Date()
  return d.toDateString() === today.toDateString()
    ? d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })
    : d.toLocaleDateString(undefined, { month: "short", day: "numeric" })
}
function timeRange(start: string, end: string, allDay?: boolean): string {
  if (allDay) return "All day"
  const f = (s: string) => { const d = new Date(s); return Number.isNaN(d.getTime()) ? s : d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" }) }
  return `${f(start)} – ${f(end)}`
}
function dayLabel(s: string): string {
  const d = new Date(s.length === 10 ? s + "T00:00:00" : s)
  return Number.isNaN(d.getTime()) ? s : d.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" })
}

function Frame({ app, title, children, testId }: { app: "gmail" | "calendar" | "drive" | "docs"; title: string; children: React.ReactNode; testId: string }) {
  const icon = { gmail: "ti-mail", calendar: "ti-calendar-event", drive: "ti-brand-google-drive", docs: "ti-file-text" }[app]
  const name = { gmail: "Gmail", calendar: "Google Calendar", drive: "Google Drive", docs: "Google Docs" }[app]
  return (
    <div className="g-card" data-testid={testId} data-app={app}>
      <div className="g-head">
        <span className={`g-app g-app-${app}`}><i className={`ti ${icon}`} /></span>
        <span className="g-app-name">{name}</span>
        <span className="g-title">{title}</span>
      </div>
      {children}
    </div>
  )
}

function Labels({ labels }: { labels?: string[] }) {
  const shown = (labels ?? []).filter((l) => !["INBOX", "UNREAD", "CATEGORY_PERSONAL", "IMPORTANT"].includes(l)).slice(0, 3)
  if (!shown.length) return null
  return <span className="g-labels">{shown.map((l) => <span key={l} className="g-label">{l.replace(/^CATEGORY_/, "").toLowerCase()}</span>)}</span>
}

function GmailList({ ui }: { ui: Extract<GoogleUi, { kind: "gmail_messages" }> }) {
  return (
    <Frame app="gmail" title={`${ui.messages.length} message${ui.messages.length === 1 ? "" : "s"}${ui.query ? ` · ${ui.query}` : ""}`} testId="gmail-list">
      <ul className="g-list">
        {ui.messages.map((m) => (
          <li key={m.id} className={`g-row${m.unread ? " is-unread" : ""}`}>
            <span className="g-avatar" style={{ background: avatarColor(senderName(m.from)) }}>{initial(m.from)}</span>
            <span className="g-from" title={m.from}>{senderName(m.from)}</span>
            <span className="g-subject">
              <span className="g-subject-text">{m.subject || "(no subject)"}</span>
              {m.snippet ? <span className="g-snippet"> – {m.snippet}</span> : null}
            </span>
            <Labels labels={m.labels} />
            <span className="g-date">{shortDate(m.date)}</span>
          </li>
        ))}
      </ul>
    </Frame>
  )
}

function GmailThread({ ui }: { ui: Extract<GoogleUi, { kind: "gmail_thread" }> }) {
  const [openIdx, setOpenIdx] = useState<number>(ui.messages.length - 1)
  return (
    <Frame app="gmail" title={ui.subject || "(no subject)"} testId="gmail-thread">
      <div className="g-thread">
        {ui.messages.map((m, i) => (
          <div key={m.id} className={`g-msg${openIdx === i ? " is-open" : ""}`}>
            <button type="button" className="g-msg-head" onClick={() => setOpenIdx(openIdx === i ? -1 : i)}>
              <span className="g-avatar" style={{ background: avatarColor(senderName(m.from)) }}>{initial(m.from)}</span>
              <span className="g-msg-from">{senderName(m.from)}<span className="g-msg-addr"> {m.from.includes("<") ? m.from.slice(m.from.indexOf("<")) : ""}</span></span>
              {openIdx !== i && m.snippet ? <span className="g-snippet g-msg-snip">{m.snippet}</span> : null}
              <span className="g-date">{shortDate(m.date)}</span>
            </button>
            {openIdx === i && (
              <div className="g-msg-body">
                {m.to ? <div className="g-msg-to">to {m.to}</div> : null}
                <div className="g-body-text">{m.body || m.snippet || ""}</div>
              </div>
            )}
          </div>
        ))}
      </div>
    </Frame>
  )
}

export function GmailCompose({ to, cc, subject, body, status }: { to?: string; cc?: string | null; subject?: string; body?: string; status: "draft" | "sent" | "pending" }) {
  const title = status === "sent" ? "Message sent" : status === "draft" ? "Saved to Drafts" : "New message"
  return (
    <div className="g-card g-compose" data-testid={`gmail-compose-${status}`}>
      <div className="g-compose-bar">
        <span>{title}</span>
        {status === "sent" ? <i className="ti ti-check" /> : status === "draft" ? <i className="ti ti-file-pencil" /> : null}
      </div>
      <div className="g-compose-field"><span className="g-compose-key">To</span><span>{to}</span></div>
      {cc ? <div className="g-compose-field"><span className="g-compose-key">Cc</span><span>{cc}</span></div> : null}
      <div className="g-compose-field g-compose-subject">{subject || "(no subject)"}</div>
      <div className="g-compose-body">{body}</div>
    </div>
  )
}

function CalendarAgenda({ ui }: { ui: Extract<GoogleUi, { kind: "calendar_events" }> }) {
  const groups = new Map<string, typeof ui.events>()
  for (const e of ui.events) {
    const k = dayLabel(e.start)
    groups.set(k, [...(groups.get(k) ?? []), e])
  }
  return (
    <Frame app="calendar" title={ui.created ? "Event created" : `${ui.events.length} event${ui.events.length === 1 ? "" : "s"}`} testId="calendar-agenda">
      <div className="g-agenda">
        {[...groups.entries()].map(([day, events]) => (
          <div key={day} className="g-day">
            <div className="g-day-label">{day}</div>
            {events.map((e, i) => (
              <a key={e.id ?? i} className="g-event" href={e.link ?? undefined} target={e.link ? "_blank" : undefined} rel="noreferrer">
                <span className="g-event-bar" />
                <span className="g-event-time">{timeRange(e.start, e.end, e.all_day)}</span>
                <span className="g-event-main">
                  <span className="g-event-title">{e.summary}</span>
                  {e.location ? <span className="g-event-sub"><i className="ti ti-map-pin" /> {e.location}</span> : null}
                  {e.attendees?.length ? <span className="g-event-sub"><i className="ti ti-users" /> {e.attendees.join(", ")}</span> : null}
                </span>
              </a>
            ))}
          </div>
        ))}
      </div>
    </Frame>
  )
}

function driveIcon(mime?: string | null) {
  if (!mime) return "ti-file"
  if (mime.includes("document")) return "ti-file-text"
  if (mime.includes("spreadsheet")) return "ti-table"
  if (mime.includes("presentation")) return "ti-presentation"
  if (mime.includes("pdf")) return "ti-file-type-pdf"
  if (mime.includes("folder")) return "ti-folder"
  if (mime.startsWith("image/")) return "ti-photo"
  return "ti-file"
}

function DriveList({ ui }: { ui: Extract<GoogleUi, { kind: "drive_files" }> }) {
  return (
    <Frame app="drive" title={`${ui.files.length} file${ui.files.length === 1 ? "" : "s"}`} testId="drive-list">
      <ul className="g-list">
        {ui.files.map((f) => (
          <li key={f.id} className="g-row">
            <span className={`g-file-icon g-mime-${f.mime?.includes("document") ? "doc" : f.mime?.includes("spreadsheet") ? "sheet" : f.mime?.includes("presentation") ? "slides" : "other"}`}><i className={`ti ${driveIcon(f.mime)}`} /></span>
            <a className="g-file-name" href={f.link ?? undefined} target={f.link ? "_blank" : undefined} rel="noreferrer">{f.name}</a>
            <span className="g-date">{f.modified ? shortDate(f.modified) : ""}</span>
          </li>
        ))}
      </ul>
    </Frame>
  )
}

function DocView({ ui }: { ui: Extract<GoogleUi, { kind: "docs_document" }> }) {
  return (
    <Frame app="docs" title={ui.title || "Untitled document"} testId="docs-view">
      <div className="g-doc-page"><div className="g-doc-text">{ui.text}</div></div>
    </Frame>
  )
}

/** Render a tool's structured result, or nothing if it is not one we style. */
export function GoogleCard({ ui }: { ui: GoogleUi }) {
  switch (ui.kind) {
    case "gmail_messages": return <GmailList ui={ui} />
    case "gmail_thread": return <GmailThread ui={ui} />
    case "gmail_draft": return <GmailCompose to={ui.to} cc={ui.cc} subject={ui.subject} body={ui.body} status="draft" />
    case "gmail_sent": return <GmailCompose to={ui.to} cc={ui.cc} subject={ui.subject} body={ui.body} status="sent" />
    case "calendar_events": return <CalendarAgenda ui={ui} />
    case "drive_files": return <DriveList ui={ui} />
    case "docs_document": return <DocView ui={ui} />
    default: return null
  }
}

export function isGoogleUi(v: unknown): v is GoogleUi {
  return Boolean(v && typeof v === "object" && typeof (v as { kind?: unknown }).kind === "string")
}
