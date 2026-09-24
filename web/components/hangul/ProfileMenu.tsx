"use client"

import { useEffect, useRef, useState } from "react"
import { signOut, useSession } from "next-auth/react"
import Link from "next/link"

type Quality = {
  available: boolean
  avg_correctness?: number
  avg_faithfulness?: number
  gate_passed?: boolean
  cases?: number
}

/**
 * The eval harness scores every prompt/model change with an LLM judge and a
 * CI gate (GET /quality). Showing the latest verdict here turns that internal
 * signal into something a user can see: how trustworthy answers are today.
 */
function QualityRow() {
  const [q, setQ] = useState<Quality | null>(null)
  useEffect(() => {
    let alive = true
    fetch("/api/quality", { signal: AbortSignal.timeout(5_000) })
      .then((r) => (r.ok ? r.json() : { available: false }))
      .then((j) => { if (alive) setQ(j) })
      .catch(() => { if (alive) setQ({ available: false }) })
    return () => { alive = false }
  }, [])
  if (!q || !q.available) return null
  const pct = (v?: number) => (typeof v === "number" ? `${Math.round(v * 100)}%` : "–")
  return (
    <div data-testid="quality-row" style={{ padding: "8px 10px", borderTop: "0.5px solid var(--surface-border)", marginTop: 6, fontSize: 12 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4 }}>
        <span style={{ fontWeight: 500 }}>Answer quality</span>
        <span
          style={{
            marginLeft: "auto", fontSize: 10, padding: "1px 6px", borderRadius: 8,
            background: q.gate_passed ? "var(--ok)" : "var(--warn)", color: "var(--solid-fg)",
          }}
        >
          {q.gate_passed ? "gate passed" : "gate failed"}
        </span>
      </div>
      <div className="h-muted" style={{ display: "flex", gap: 10 }}>
        <span>Correct {pct(q.avg_correctness)}</span>
        <span>Faithful {pct(q.avg_faithfulness)}</span>
        {typeof q.cases === "number" && <span>{q.cases} cases</span>}
      </div>
    </div>
  )
}

/**
 * Avatar button with a small menu: who is signed in, and Sign out. Signing
 * out always returns to the landing page.
 */
export function ProfileMenu() {
  const { data: session } = useSession()
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener("mousedown", onDoc)
    return () => document.removeEventListener("mousedown", onDoc)
  }, [open])

  const user = session?.user
  if (!user) return null

  const name = user.name ?? user.email ?? "You"
  const initial = name.trim().charAt(0).toUpperCase()

  return (
    <div ref={ref} style={{ position: "relative" }}>
      <button
        onClick={() => setOpen((o) => !o)}
        aria-label="Account menu"
        aria-expanded={open}
        style={{
          width: 32, height: 32, borderRadius: "50%", padding: 0, cursor: "pointer",
          border: "0.5px solid var(--surface-border)", background: "var(--solid-bg)",
          color: "var(--solid-fg)", overflow: "hidden", display: "flex",
          alignItems: "center", justifyContent: "center", fontSize: 13, fontWeight: 600,
        }}
      >
        {user.image ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={user.image} alt="" referrerPolicy="no-referrer" style={{ width: "100%", height: "100%", objectFit: "cover" }} />
        ) : (
          initial
        )}
      </button>

      {open && (
        <div className="h-popover" style={{ position: "absolute", top: 40, right: 0, minWidth: 220, zIndex: 30 }}>
          <div style={{ padding: "8px 10px 10px", borderBottom: "0.5px solid var(--surface-border)", marginBottom: 6 }}>
            <div style={{ fontSize: 13, fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{user.name ?? "Signed in"}</div>
            {user.email && (
              <div className="h-muted" style={{ fontSize: 12, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{user.email}</div>
            )}
          </div>
          <Link
            href="/settings"
            className="h-btn-ghost"
            style={{ width: "100%", justifyContent: "flex-start", padding: "8px 10px", textDecoration: "none" }}
            onClick={() => setOpen(false)}
          >
            <i className="ti ti-adjustments" style={{ fontSize: 15 }} />
            Personalisation & tasks
          </Link>
          <Link
            href="/vault"
            className="h-btn-ghost"
            style={{ width: "100%", justifyContent: "flex-start", padding: "8px 10px", textDecoration: "none" }}
            onClick={() => setOpen(false)}
          >
            <i className="ti ti-key" style={{ fontSize: 15 }} />
            Connected services
          </Link>
          <button
            className="h-btn-ghost"
            style={{ width: "100%", justifyContent: "flex-start", padding: "8px 10px" }}
            onClick={() => signOut({ redirectTo: "/" })}
          >
            <i className="ti ti-logout" style={{ fontSize: 15 }} />
            Sign out
          </button>
          <QualityRow />
        </div>
      )}
    </div>
  )
}
