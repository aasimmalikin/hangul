"use client"

import { useEffect, useState } from "react"
import { disablePush, enablePush, pushState, testPush, type PushState } from "@/lib/push"

/**
 * Settings → Notifications: turn notifications on for this device, so
 * reminders and the morning brief arrive even when Hangul is closed. Free on
 * every plan. Hidden while the server has no push set up.
 */
export function PushToggle({ frame }: { frame: (content: React.ReactNode) => React.ReactNode }) {
  const [state, setState] = useState<PushState | null>(null)
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState<string | null>(null)

  useEffect(() => { void pushState().then(setState) }, [])

  const run = async (fn: () => Promise<PushState>, after?: string) => {
    setBusy(true); setNote(null)
    const next = await fn()
    setState(next); setBusy(false)
    if (after && next === "on") setNote(after)
  }
  const test = async () => {
    setBusy(true); setNote(null)
    const sent = await testPush()
    setBusy(false)
    setNote(sent ? "Sent. It should appear in a few seconds." : "Couldn't reach this device. Try turning notifications off and on.")
  }

  if (state === null || state === "off") return null
  return frame(
    <div style={{ display: "flex", flexDirection: "column", gap: 10, fontSize: 13 }} data-testid="push-toggle" data-state={state}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <i className={state === "on" ? "ti ti-bell-ringing" : "ti ti-bell"} style={{ fontSize: 18 }} />
        <span style={{ flex: 1, minWidth: 200 }}>
          {state === "on" && "On for this device. Reminders and your brief arrive here even when Hangul is closed."}
          {state === "available" && "Get reminders and your brief on this device, even when Hangul is closed."}
          {state === "blocked" && "Notifications are blocked for Hangul. Allow them in your browser’s site settings, then come back."}
          {state === "needs-install" && <>On iPhone, add Hangul to your Home Screen first: tap <i className="ti ti-share-2" /> <b style={{ fontWeight: 500 }}>Share</b>, then <b style={{ fontWeight: 500 }}>Add to Home Screen</b>, and open it from there.</>}
          {state === "unsupported" && "This browser can’t show notifications from Hangul. Try Chrome, Edge, Firefox or Safari."}
        </span>
        {state === "available" && (
          <button className="h-btn-solid" disabled={busy} onClick={() => void run(enablePush, "Done. You’ll get your next reminder here.")} data-testid="push-on">
            Turn on
          </button>
        )}
        {state === "on" && (
          <>
            <button className="h-btn-ghost" style={{ fontSize: 12 }} disabled={busy} onClick={() => void test()} data-testid="push-test">Send a test</button>
            <button className="h-btn-ghost" style={{ fontSize: 12 }} disabled={busy} onClick={() => void run(disablePush)} data-testid="push-off">Turn off</button>
          </>
        )}
      </div>
      {note && <span className="h-muted" style={{ fontSize: 12 }} role="status">{note}</span>}
    </div>
  )
}
