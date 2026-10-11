"use client"

import { useState } from "react"
import { HangulSigil } from "@/components/HangulSigil"

export type ToolActivity = {
  tool: string
  arguments?: Record<string, unknown>
  /**
   * pending   the model is still writing the call (arguments arrive live)
   * running   the tool is executing
   * awaiting  parked until the user approves it
   * skipped   not run because an earlier call needs approval
   */
  status: "pending" | "running" | "done" | "error" | "awaiting" | "skipped"
  drafting?: boolean
  preview?: string
  ms?: number
  cached?: boolean
  /** Structured result for a rich card (Google Workspace and everyday tools). */
  ui?: GoogleUi | DailyUi
}

import type { GoogleUi } from "@/components/hangul/GoogleCards"
import type { DailyUi } from "@/components/hangul/DailyCards"

type Labels = { pending: string; running: string; done: string; awaiting: string }

const TOOL_LABELS: Record<string, Labels> = {
  web_search: { pending: "Preparing a web search", running: "Searching the web", done: "Searched the web", awaiting: "Wants to search the web" },
  search_docs: { pending: "Preparing a document search", running: "Searching your documents", done: "Searched your documents", awaiting: "Wants to search your documents" },
  calculator: { pending: "Setting up a calculation", running: "Calculating", done: "Calculated", awaiting: "Wants to calculate" },
  ask_user: { pending: "Preparing a question for you", running: "Waiting on you", done: "Asked you", awaiting: "Has a question for you" },
  my_files: { pending: "Preparing to look at your files", running: "Looking at your files", done: "Looked at your files", awaiting: "Wants to look at your files" },
  // older chats still show the MCP filesystem tools they used
  filesystem__write_file: { pending: "Drafting a file", running: "Writing a file", done: "Wrote a file", awaiting: "Wants to write a file" },
  filesystem__edit_file: { pending: "Drafting an edit", running: "Editing a file", done: "Edited a file", awaiting: "Wants to edit a file" },
  filesystem__create_directory: { pending: "Preparing a folder", running: "Creating a folder", done: "Created a folder", awaiting: "Wants to create a folder" },
  filesystem__move_file: { pending: "Preparing to move a file", running: "Moving a file", done: "Moved a file", awaiting: "Wants to move a file" },
  filesystem__read_file: { pending: "Preparing to read a file", running: "Reading a file", done: "Read a file", awaiting: "Wants to read a file" },
  filesystem__read_text_file: { pending: "Preparing to read a file", running: "Reading a file", done: "Read a file", awaiting: "Wants to read a file" },
  filesystem__list_directory: { pending: "Preparing to list files", running: "Listing files", done: "Listed files", awaiting: "Wants to list files" },
  filesystem__search_files: { pending: "Preparing a file search", running: "Looking through files", done: "Looked through files", awaiting: "Wants to look through files" },
  remember: { pending: "Preparing a memory", running: "Saving to memory", done: "Saved to memory", awaiting: "Wants to save to memory" },
  recall: { pending: "Preparing to check memory", running: "Checking memory", done: "Checked memory", awaiting: "Wants to check memory" },
  recall_episodes: { pending: "Preparing to look back", running: "Looking at past conversations", done: "Looked at past conversations", awaiting: "Wants to look at past conversations" },
  gmail__replies_owed: { pending: "Preparing to check your replies", running: "Finding emails waiting on you", done: "Found emails waiting on you", awaiting: "Wants to check your replies" },
  gmail__search_messages: { pending: "Preparing a Gmail search", running: "Searching Gmail", done: "Searched Gmail", awaiting: "Wants to search Gmail" },
  gmail__get_thread: { pending: "Preparing to open a thread", running: "Reading a Gmail thread", done: "Read a Gmail thread", awaiting: "Wants to read a Gmail thread" },
  gmail__get_message: { pending: "Preparing to open an email", running: "Reading an email", done: "Read an email", awaiting: "Wants to read an email" },
  gmail__create_draft: { pending: "Drafting an email", running: "Saving a draft", done: "Saved a draft", awaiting: "Wants to save a draft" },
  gmail__send_message: { pending: "Drafting an email", running: "Sending an email", done: "Sent an email", awaiting: "Wants to send an email" },
  gmail__send_draft: { pending: "Preparing to send a draft", running: "Sending a draft", done: "Sent a draft", awaiting: "Wants to send a draft" },
  calendar__list_events: { pending: "Preparing to check the calendar", running: "Checking Google Calendar", done: "Checked Google Calendar", awaiting: "Wants to check the calendar" },
  calendar__create_event: { pending: "Drafting an event", running: "Creating an event", done: "Created an event", awaiting: "Wants to create an event" },
  drive__search_files: { pending: "Preparing a Drive search", running: "Searching Google Drive", done: "Searched Google Drive", awaiting: "Wants to search Drive" },
  drive__get_file: { pending: "Preparing to open a file", running: "Reading a Drive file", done: "Read a Drive file", awaiting: "Wants to read a Drive file" },
  docs__get_document: { pending: "Preparing to open a doc", running: "Reading a Google Doc", done: "Read a Google Doc", awaiting: "Wants to read a Google Doc" },
  docs__append_text: { pending: "Drafting text for a doc", running: "Editing a Google Doc", done: "Edited a Google Doc", awaiting: "Wants to edit a Google Doc" },
  calendar__find_free_time: { pending: "Preparing to check your free time", running: "Finding free time", done: "Found free time", awaiting: "Wants to check your calendar" },
  calendar__update_event: { pending: "Drafting a change", running: "Updating an event", done: "Updated an event", awaiting: "Wants to change an event" },
  calendar__delete_event: { pending: "Preparing to cancel an event", running: "Deleting an event", done: "Deleted an event", awaiting: "Wants to delete an event" },
  sheets__find_spreadsheets: { pending: "Preparing a Sheets search", running: "Searching Google Sheets", done: "Searched Google Sheets", awaiting: "Wants to search Sheets" },
  sheets__read_range: { pending: "Preparing to open a sheet", running: "Reading a Google Sheet", done: "Read a Google Sheet", awaiting: "Wants to read a sheet" },
  sheets__append_rows: { pending: "Drafting rows", running: "Adding rows to a sheet", done: "Added rows to a sheet", awaiting: "Wants to add rows to a sheet" },
  sheets__create_spreadsheet: { pending: "Drafting a spreadsheet", running: "Creating a Google Sheet", done: "Created a Google Sheet", awaiting: "Wants to create a spreadsheet" },
  contacts__search: { pending: "Preparing a contact search", running: "Looking up contacts", done: "Looked up contacts", awaiting: "Wants to look up contacts" },
  meet__create_meeting: { pending: "Preparing a Meet link", running: "Making a Google Meet link", done: "Made a Google Meet link", awaiting: "Wants to make a Meet link" },
  meet__recent_meetings: { pending: "Preparing to check your calls", running: "Checking your Google Meet calls", done: "Checked your Google Meet calls", awaiting: "Wants to check your calls" },
  meet__get_transcript: { pending: "Preparing to read a call", running: "Reading the call's transcript", done: "Read the call's transcript", awaiting: "Wants to read a call's transcript" },
  generate_image: { pending: "Planning the image", running: "Drawing your image", done: "Drew your image", awaiting: "Wants to draw an image" },
  maps_search: { pending: "Preparing a map search", running: "Searching the map", done: "Searched the map", awaiting: "Wants to search the map" },
  travel_time: { pending: "Preparing a route", running: "Working out the route", done: "Worked out the route", awaiting: "Wants to check a route" },
  github__search: { pending: "Preparing a GitHub search", running: "Searching GitHub", done: "Searched GitHub", awaiting: "Wants to search GitHub" },
  github__my_work: { pending: "Preparing your GitHub queue", running: "Checking your GitHub work", done: "Checked your GitHub work", awaiting: "Wants to check GitHub" },
  github__get_issue: { pending: "Preparing to open an issue", running: "Reading a GitHub issue", done: "Read a GitHub issue", awaiting: "Wants to read an issue" },
  github__create_issue: { pending: "Drafting an issue", running: "Opening an issue", done: "Opened an issue", awaiting: "Wants to open an issue" },
  github__comment: { pending: "Drafting a comment", running: "Commenting on GitHub", done: "Commented on GitHub", awaiting: "Wants to comment on GitHub" },
  notion__search: { pending: "Preparing a Notion search", running: "Searching Notion", done: "Searched Notion", awaiting: "Wants to search Notion" },
  notion__read_page: { pending: "Preparing to open a page", running: "Reading a Notion page", done: "Read a Notion page", awaiting: "Wants to read a Notion page" },
  notion__append_to_page: { pending: "Drafting text for Notion", running: "Adding to a Notion page", done: "Added to a Notion page", awaiting: "Wants to add to a Notion page" },
  notion__create_page: { pending: "Drafting a page", running: "Creating a Notion page", done: "Created a Notion page", awaiting: "Wants to create a Notion page" },
  slack__search_messages: { pending: "Preparing a Slack search", running: "Searching Slack", done: "Searched Slack", awaiting: "Wants to search Slack" },
  slack__list_channels: { pending: "Preparing to list channels", running: "Listing Slack channels", done: "Listed Slack channels", awaiting: "Wants to list channels" },
  slack__read_channel: { pending: "Preparing to open a channel", running: "Reading a Slack channel", done: "Read a Slack channel", awaiting: "Wants to read a channel" },
  slack__send_message: { pending: "Drafting a message", running: "Posting to Slack", done: "Posted to Slack", awaiting: "Wants to post to Slack" },
  reminders: { pending: "Preparing a reminder", running: "Updating your reminders", done: "Updated your reminders", awaiting: "Wants to set a reminder" },
  lists: { pending: "Preparing your list", running: "Updating your list", done: "Updated your list", awaiting: "Wants to change your list" },
  notes: { pending: "Preparing a note", running: "Checking your notes", done: "Checked your notes", awaiting: "Wants to use your notes" },
  read_webpage: { pending: "Preparing to open a link", running: "Reading the page", done: "Read the page", awaiting: "Wants to open a link" },
  weather: { pending: "Preparing a forecast", running: "Checking the weather", done: "Checked the weather", awaiting: "Wants to check the weather" },
  convert: { pending: "Preparing a conversion", running: "Converting", done: "Converted", awaiting: "Wants to convert" },
  world_clock: { pending: "Preparing the world clock", running: "Checking times", done: "Checked times", awaiting: "Wants to check times" },
  view_image: { pending: "Preparing to look at an image", running: "Looking at your image", done: "Looked at your image", awaiting: "Wants to look at your image" },
  create_file: { pending: "Drafting your file", running: "Creating your file", done: "Created your file", awaiting: "Wants to create a file" },
  analyze_data: { pending: "Preparing the analysis", running: "Analysing your data", done: "Analysed your data", awaiting: "Wants to analyse your data" },
}

/** Human name for a tool id: "filesystem__write_file" → "write file". */
export function toolName(tool: string): string {
  return tool.replace(/^filesystem__/, "").replace(/^(gmail|calendar|drive|docs|sheets|contacts|github|notion|slack)__/, "$1 ").replace(/_/g, " ")
}

export function label(a: ToolActivity): string {
  const entry = TOOL_LABELS[a.tool]
  if (!entry) {
    const n = toolName(a.tool)
    return a.status === "pending" ? `Preparing ${n}` : a.status === "awaiting" ? `Wants to run ${n}` : a.status === "running" ? `Running ${n}` : `Ran ${n}`
  }
  switch (a.status) {
    case "pending": return entry.pending
    case "running": return entry.running
    case "awaiting": return entry.awaiting
    case "skipped": return entry.awaiting
    default: return entry.done
  }
}

/** The one argument worth showing inline — the query, the path, the expression. */
function detail(a: ToolActivity): string | null {
  const args = a.arguments ?? {}
  for (const k of ["query", "expression", "question", "path", "pattern", "source", "subject", "summary", "thread_id", "file_id", "document_id"]) {
    const v = args[k]
    if (typeof v === "string" && v.trim()) {
      return k === "path" || k === "source" ? v.split("/").slice(-1)[0] : v
    }
  }
  return null
}

/** Long-form argument to show as it is drafted — a file's content, an edit. */
function draft(a: ToolActivity): string | null {
  const args = a.arguments ?? {}
  if (typeof args.content === "string") return args.content
  if (Array.isArray(args.edits)) {
    return args.edits
      .map((e) => (e && typeof e === "object" ? `- ${String((e as Record<string, unknown>).oldText ?? "")}\n+ ${String((e as Record<string, unknown>).newText ?? "")}` : ""))
      .join("\n\n")
  }
  return null
}

function Spinner() {
  return (
    <span
      className="h-3 w-3 shrink-0 animate-spin rounded-full border-2"
      style={{ borderColor: "var(--surface-border)", borderTopColor: "var(--fg)" }}
    />
  )
}

function StatusIcon({ status }: { status: ToolActivity["status"] }) {
  if (status === "pending" || status === "running") return <Spinner />
  if (status === "awaiting")
    return <i className="ti ti-hand-stop shrink-0" style={{ color: "var(--warn)", fontSize: 13, width: 12, textAlign: "center" }} />
  if (status === "skipped")
    return <span className="h-3 w-3 shrink-0 text-center text-xs leading-3" style={{ color: "var(--faint)" }}>–</span>
  if (status === "error")
    return <span className="h-3 w-3 shrink-0 text-center text-xs leading-3" style={{ color: "var(--err)" }}>✕</span>
  return <span className="h-3 w-3 shrink-0 text-center text-xs leading-3" style={{ color: "var(--ok)" }}>✓</span>
}

/**
 * One line of the agent's live activity: what it is doing, on what, and — once
 * finished — a peek at what came back. While the model is still writing the
 * call, the draft of its long argument (a file's content) streams underneath.
 */
export function ToolRow({ activity }: { activity: ToolActivity }) {
  const [open, setOpen] = useState(false)
  const d = detail(activity)
  const live = activity.status === "pending" || activity.status === "running"
  const draftText = live ? draft(activity) : null
  const expandable = Boolean(activity.preview) && !live

  return (
    <div className="my-1 text-sm" data-testid="tool-row" data-status={activity.status}>
      <button
        type="button"
        onClick={() => expandable && setOpen((o) => !o)}
        disabled={!expandable}
        className="flex w-full items-center gap-2 rounded-md px-1.5 py-1 text-left disabled:cursor-default"
        style={{ color: activity.status === "skipped" ? "var(--faint)" : "var(--muted)" }}
        onMouseEnter={(e) => { if (expandable) e.currentTarget.style.background = "var(--surface-hover)" }}
        onMouseLeave={(e) => { e.currentTarget.style.background = "transparent" }}
      >
        <StatusIcon status={activity.status} />
        <span className={live ? "animate-pulse" : ""}>{label(activity)}</span>
        {d && (
          <span className="truncate" style={{ color: "var(--faint)" }} title={d}>
            {d}
          </span>
        )}
        {activity.status === "awaiting" && (
          <span className="ml-auto shrink-0 text-xs" style={{ color: "var(--warn)" }}>needs your approval</span>
        )}
        {activity.status === "skipped" && (
          <span className="ml-auto shrink-0 text-xs" style={{ color: "var(--faint)" }}>not run yet</span>
        )}
        {(activity.status === "done" || activity.status === "error") && activity.ms ? (
          <span className="ml-auto shrink-0 text-xs" style={{ color: "var(--faint)" }}>
            {activity.ms < 1000 ? `${activity.ms}ms` : `${(activity.ms / 1000).toFixed(1)}s`}
          </span>
        ) : null}
      </button>

      {draftText !== null && (
        <pre
          data-testid="tool-draft"
          className="mt-1 max-h-60 overflow-auto whitespace-pre-wrap rounded-lg p-2 text-xs"
          style={{ background: "var(--bubble)", border: "0.5px solid var(--surface-border)", color: "var(--fg)", fontFamily: "var(--font-geist-mono)" }}
        >
          {draftText}
          {activity.status === "pending" && <span className="animate-pulse">▍</span>}
        </pre>
      )}

      {open && activity.preview && (
        <pre
          className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap rounded-lg p-2 text-xs"
          style={{ background: "var(--bubble)", border: "0.5px solid var(--surface-border)", color: "var(--muted)" }}
        >
          {activity.preview}
        </pre>
      )}
    </div>
  )
}

// ------------------------------------------------------------ activity group

export type ActivityItem =
  | { kind: "tool"; key: string; activity: ToolActivity }
  | { kind: "thinking"; key: string; step?: number }

function fmtMs(ms: number) {
  return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`
}

/** "Searched your documents, read a file" — each distinct finished step, once. */
function summarise(tools: ToolActivity[]): string {
  const seen = new Set<string>()
  const parts: string[] = []
  for (const t of tools) {
    if (t.status === "skipped") continue
    const l = label(t)
    if (seen.has(l)) continue
    seen.add(l)
    parts.push(parts.length === 0 ? l : l.charAt(0).toLowerCase() + l.slice(1))
  }
  return parts.join(", ")
}

/**
 * One run's activity as a single compact block, the way a chat UI keeps its
 * "thinking" from taking over the thread:
 *
 * - live: one line with the *current* step (breathing sigil + shimmering
 *   text), earlier steps folded underneath
 * - done: one line summarising what was done ("Searched the web, read a
 *   file · 3 steps · 2.4s")
 *
 * A chevron expands the individual rows. Anything that needs the user —
 * a file being drafted, an action awaiting approval, an error — unfolds
 * itself so it is never hidden behind the summary.
 */
export function ActivityGroup({ items, live }: { items: ActivityItem[]; live: boolean }) {
  const [userOpen, setUserOpen] = useState<boolean | null>(null)
  const tools = items.filter((i): i is Extract<ActivityItem, { kind: "tool" }> => i.kind === "tool").map((i) => i.activity)
  const attention = tools.some((t) => t.status === "awaiting" || t.status === "error" || (t.status === "pending" && draft(t) !== null))
  const open = userOpen ?? attention
  const current = items[items.length - 1]
  const steps = tools.length
  const totalMs = tools.reduce((n, t) => n + (t.ms ?? 0), 0)

  let headline: React.ReactNode
  let sub: string | null = null
  let thinking = false
  if (live && current?.kind === "thinking") {
    thinking = true
    headline = current.step && current.step > 1 ? "Thinking about the next step…" : "Thinking…"
    sub = current.step ? `step ${current.step}` : null
  } else if (live && current?.kind === "tool") {
    headline = label(current.activity)
    sub = detail(current.activity)
  } else if (steps === 0) {
    headline = "Thought it through"
  } else {
    headline = summarise(tools) || "Worked through it"
    sub = [steps > 1 ? `${steps} steps` : null, totalMs ? fmtMs(totalMs) : null].filter(Boolean).join(" · ") || null
  }

  return (
    <div className={`h-activity${live ? " is-live" : ""}`} data-testid="activity" data-live={live} data-open={open}>
      <button type="button" className="h-activity-head" onClick={() => setUserOpen(!open)} aria-expanded={open}>
        <span className={`h-activity-sigil${live ? " h-sigil-live" : ""}`} aria-hidden>
          <HangulSigil size={14} />
        </span>
        <span className={live ? "h-shimmer" : ""} data-testid={thinking ? "thinking" : undefined} style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {headline}
          {thinking && sub ? <span style={{ color: "var(--faint)", fontSize: 11, marginLeft: 6 }}>{sub}</span> : null}
        </span>
        {!thinking && sub ? <span className="truncate" style={{ color: "var(--faint)", fontSize: 12 }} title={sub}>{sub}</span> : null}
        {steps > 0 && (
          <i className={`ti ti-chevron-down h-activity-chev${open ? " is-open" : ""}`} style={{ marginLeft: "auto", fontSize: 14, flexShrink: 0 }} />
        )}
      </button>
      {open && steps > 0 && (
        <div className="h-activity-body" data-testid="activity-rows">
          {items.map((i) => (i.kind === "tool" ? <ToolRow key={i.key} activity={i.activity} /> : null))}
        </div>
      )}
    </div>
  )
}
