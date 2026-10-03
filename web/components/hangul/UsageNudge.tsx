"use client"

import Link from "next/link"
import { useEffect, useState } from "react"

/**
 * The "running low" card: shown in the chat once 80% of the period's
 * allowance is used (GET /billing `nudge`), before the user hits the wall.
 * Re-checked after every finished answer; dismissing hides it for this tab
 * until the numbers change period (keyed by plan + total).
 */
type Billing = { enabled?: boolean; plan?: string; nudge?: boolean; messages_left?: number; messages_total?: number; trial_days?: number }

const KEY = "hangul:nudge-dismissed"

export function UsageNudge({ refreshKey }: { refreshKey: number }) {
  const [b, setB] = useState<Billing | null>(null)
  // read once; nothing renders before /api/billing answers, so there is no hydration mismatch
  const [dismissed, setDismissed] = useState<string | null>(() => {
    try { return sessionStorage.getItem(KEY) } catch { return null }   // private mode / server render
  })

  useEffect(() => {
    let alive = true
    void fetch("/api/billing", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then((body: Billing | null) => { if (alive) setB(body) })
      .catch(() => {})
    return () => { alive = false }
  }, [refreshKey])

  if (!b?.enabled || !b.nudge) return null
  const id = `${b.plan}:${b.messages_total}`
  if (dismissed === id) return null
  const next = b.plan === "plus" ? "pro" : "plus"
  const label = next === "pro" ? "Pro" : "Plus"
  const cta = next === "plus" && b.trial_days ? `Start ${b.trial_days}-day free trial` : `Upgrade to ${label}`

  return (
    <div className="rounded-xl p-3" data-testid="usage-nudge"
      style={{ background: "var(--surface)", border: "0.5px solid var(--surface-border)" }}>
      <p className="text-sm" style={{ margin: 0 }}>
        <i className="ti ti-gauge" style={{ fontSize: 13, marginRight: 6 }} />
        You&apos;ve used most of this {b.plan === "free" ? "month" : "period"}&apos;s messages: about {b.messages_left ?? 0} left.
        {" "}{label} gives you {next === "pro" ? "five times as many" : "far more"}.
      </p>
      <div className="flex gap-2" style={{ marginTop: 8, flexWrap: "wrap" }}>
        <Link href={`/billing?upgrade=${next}`} className="h-btn-solid" style={{ textDecoration: "none" }} data-testid="usage-nudge-upgrade">
          {cta}
        </Link>
        <button className="h-btn-ghost" data-testid="usage-nudge-dismiss" onClick={() => {
          setDismissed(id)
          try { sessionStorage.setItem(KEY, id) } catch { /* private mode */ }
        }}>Not now</button>
      </div>
    </div>
  )
}
