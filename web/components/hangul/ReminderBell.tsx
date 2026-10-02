"use client"

import Link from "next/link"
import { useCallback, useEffect, useRef, useState } from "react"
import { deviceTimeZone } from "@/lib/timezone"

type Due = { id: number; text: string; due_at: string }

const POLL_MS = 60_000

/**
 * The header bell: reminders that have fired and not been dismissed. Polls
 * `/api/reminders?scope=due` once a minute (the scheduler fires them on the
 * same cadence) and, if the browser already allows notifications, raises a
 * system notification for each new one. Nothing to set up for the user.
 */
export function ReminderBell() {
  const [due, setDue] = useState<Due[]>([])
  const [open, setOpen] = useState(false)
  const seen = useRef<Set<number>>(new Set())
  const first = useRef(true)
  const ref = useRef<HTMLDivElement>(null)

  const load = useCallback(async () => {
    try {
      const res = await fetch("/api/reminders?scope=due", { cache: "no-store" })
      if (!res.ok) return
      const rows: Due[] = await res.json()
      // A system notification for reminders that fired since the last poll
      // (not for the backlog present when the page opened).
      for (const r of rows) {
        if (!seen.current.has(r.id) && !first.current && typeof Notification !== "undefined"
            && Notification.permission === "granted") {
          try { new Notification("⏰ Reminder", { body: r.text, tag: `reminder-${r.id}` }) } catch { /* unsupported */ }
        }
        seen.current.add(r.id)
      }
      first.current = false
      setDue(rows)
    } catch { /* offline: try next poll */ }
  }, [])

  // Tell the server where this device is, once per page load, so reminders,
  // emails and scheduled tasks use the user's local time (ignored server-side
  // when they pinned a timezone in Personalisation).
  useEffect(() => {
    const timezone = deviceTimeZone()
    if (timezone) {
      void fetch("/api/settings/timezone", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ timezone }),
        keepalive: true,
      }).then((r) => r.text()).catch(() => null)     // read the body so the request completes
    }
  }, [])

  useEffect(() => {
    // Poll on a timer (and once now); state is set after the await.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load()
    const t = setInterval(() => void load(), POLL_MS)
    return () => clearInterval(t)
  }, [load])

  useEffect(() => {
    if (!open) return
    const onDoc = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false) }
    document.addEventListener("mousedown", onDoc)
    return () => document.removeEventListener("mousedown", onDoc)
  }, [open])

  const dismiss = async (id: number) => {
    setDue((xs) => xs.filter((x) => x.id !== id))
    await fetch(`/api/reminders/${id}/done`, { method: "POST" }).catch(() => null)
  }

  const askPermission = () => {
    if (typeof Notification !== "undefined" && Notification.permission === "default") void Notification.requestPermission()
  }

  return (
    <div ref={ref} style={{ position: "relative" }}>
      <button className="h-btn-ghost" aria-label={due.length ? `${due.length} reminders` : "Reminders"}
        data-testid="reminder-bell" onClick={() => { setOpen((o) => !o); askPermission() }}
        style={{ position: "relative", width: 34, height: 34, padding: 0, justifyContent: "center" }}>
        <i className="ti ti-bell" style={{ fontSize: 17 }} />
        {due.length > 0 && (
          <span data-testid="reminder-count" style={{
            position: "absolute", top: 3, right: 3, minWidth: 16, height: 16, borderRadius: 999, fontSize: 10,
            display: "grid", placeItems: "center", background: "var(--err)", color: "var(--solid-fg)", padding: "0 4px",
          }}>{due.length}</span>
        )}
      </button>
      {open && (
        <div className="h-popover" style={{ position: "absolute", top: 40, right: 0, width: 300, zIndex: 30, padding: 6 }}>
          {due.length === 0 ? (
            <div className="h-muted" style={{ fontSize: 13, padding: "8px 10px" }}>
              No reminders right now. Try “remind me to stretch in 30 minutes”.
            </div>
          ) : due.map((r) => (
            <div key={r.id} data-testid={`due-${r.id}`} style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 10px" }}>
              <i className="ti ti-alarm" style={{ fontSize: 15 }} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 13 }}>{r.text}</div>
                <div className="h-muted" style={{ fontSize: 11 }}>{new Date(r.due_at).toLocaleString(undefined, { weekday: "short", hour: "numeric", minute: "2-digit" })}</div>
              </div>
              <button className="h-btn-ghost" style={{ fontSize: 12, padding: "4px 8px" }} onClick={() => void dismiss(r.id)}>Done</button>
            </div>
          ))}
          <Link href="/lists" className="h-btn-ghost" onClick={() => setOpen(false)}
            style={{ width: "100%", justifyContent: "center", fontSize: 12, marginTop: 4, textDecoration: "none" }}>
            Lists, notes & reminders
          </Link>
        </div>
      )}
    </div>
  )
}
