"use client"

import { useState } from "react"

export type ToolActivity = {
  tool: string
  arguments?: Record<string, unknown>
  status: "running" | "done" | "error"
  preview?: string
  ms?: number
  cached?: boolean
}

const TOOL_LABELS: Record<string, { running: string; done: string }> = {
  web_search: { running: "Searching the web", done: "Searched the web" },
  search_docs: { running: "Searching your documents", done: "Searched your documents" },
  calculator: { running: "Calculating", done: "Calculated" },
  ask_user: { running: "Waiting on you", done: "Asked you" },
  filesystem__write_file: { running: "Writing a file", done: "Wrote a file" },
  filesystem__edit_file: { running: "Editing a file", done: "Edited a file" },
  filesystem__read_file: { running: "Reading a file", done: "Read a file" },
  filesystem__read_text_file: { running: "Reading a file", done: "Read a file" },
  filesystem__list_directory: { running: "Listing files", done: "Listed files" },
  filesystem__search_files: { running: "Looking through files", done: "Looked through files" },
  remember: { running: "Saving to memory", done: "Saved to memory" },
  recall: { running: "Checking memory", done: "Checked memory" },
  recall_episodes: { running: "Looking at past conversations", done: "Looked at past conversations" },
}

function label(a: ToolActivity): string {
  const entry = TOOL_LABELS[a.tool]
  if (!entry) return a.tool.replace(/^filesystem__/, "").replace(/_/g, " ")
  return a.status === "running" ? entry.running : entry.done
}

/** The one argument worth showing inline — the query, the path, the expression. */
function detail(a: ToolActivity): string | null {
  const args = a.arguments ?? {}
  for (const k of ["query", "expression", "question", "path", "pattern"]) {
    const v = args[k]
    if (typeof v === "string" && v.trim()) {
      return k === "path" ? v.split("/").slice(-1)[0] : v
    }
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
  if (status === "running") return <Spinner />
  if (status === "error")
    return <span className="h-3 w-3 shrink-0 text-center text-xs leading-3" style={{ color: "var(--err)" }}>✕</span>
  return <span className="h-3 w-3 shrink-0 text-center text-xs leading-3" style={{ color: "var(--ok)" }}>✓</span>
}

/**
 * One line of the agent's live activity: what it is doing, on what, and — once
 * finished — a peek at what came back.
 */
export function ToolRow({ activity }: { activity: ToolActivity }) {
  const [open, setOpen] = useState(false)
  const d = detail(activity)
  const expandable = Boolean(activity.preview) && activity.status !== "running"

  return (
    <div className="my-1 text-sm">
      <button
        type="button"
        onClick={() => expandable && setOpen((o) => !o)}
        disabled={!expandable}
        className="flex w-full items-center gap-2 rounded-md px-1.5 py-1 text-left disabled:cursor-default"
        style={{ color: "var(--muted)" }}
        onMouseEnter={(e) => { if (expandable) e.currentTarget.style.background = "var(--surface-hover)" }}
        onMouseLeave={(e) => { e.currentTarget.style.background = "transparent" }}
      >
        <StatusIcon status={activity.status} />
        <span className={activity.status === "running" ? "animate-pulse" : ""}>
          {label(activity)}
        </span>
        {d && (
          <span className="truncate" style={{ color: "var(--faint)" }} title={d}>
            {d}
          </span>
        )}
        {activity.status !== "running" && activity.ms ? (
          <span className="ml-auto shrink-0 text-xs" style={{ color: "var(--faint)" }}>
            {activity.ms < 1000 ? `${activity.ms}ms` : `${(activity.ms / 1000).toFixed(1)}s`}
          </span>
        ) : null}
      </button>

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
