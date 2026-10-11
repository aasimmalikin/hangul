"use client"

import Link from "next/link"
import { useCallback, useEffect, useState } from "react"

/**
 * The shop on Today (design direction A, "Ledger"): one big number first.
 *   - Today's sales: what's logged today (or "not logged yet" with yesterday's),
 *     against the same day last week and the break-even, ↑/↓ always with words.
 *   - Tomorrow: the forecast and, on a slow day, a way to the offer.
 *   - "Log sales": a floating button that opens a two-field form and saves the
 *     day straight to How's business (POST /api/business/<id>/days), with no
 *     model call; "Say it" opens voice in the chat instead.
 * Built from GET /api/business and the first usable business's overview. With
 * no business yet, one card asks to set it up. Nothing here fails Today: a
 * request that fails just leaves the card out.
 */

type Day = { day: string; sales: number; bills: number | null; closed: boolean }
type Overview = {
  business: { id: number; name: string }
  today: string
  tomorrow: string
  days: Day[]
  plan: { breakeven?: number | null } | null
  forecast: { status: string; value?: number | null; low?: number | null; high?: number | null; days_needed?: number } | null
  slow: { slow: boolean } | null
  access: { forecast: boolean }
}

const rs = (v: number) => `₹${Math.round(v).toLocaleString("en-IN")}`
const weekday = (iso: string) => new Date(`${iso}T12:00:00`).toLocaleDateString("en-IN", { weekday: "long" })
const shift = (iso: string, days: number) => {
  const d = new Date(`${iso}T12:00:00`)
  d.setDate(d.getDate() + days)
  return d.toISOString().slice(0, 10)
}

export function ShopToday() {
  const [ov, setOv] = useState<Overview | null>(null)
  const [none, setNone] = useState(false)
  const [open, setOpen] = useState(false)
  const [sales, setSales] = useState("")
  const [bills, setBills] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    const list = await fetch("/api/business", { cache: "no-store" }).then((r) => (r.ok ? r.json() : null)).catch(() => null)
    const b = (list?.businesses ?? []).find((x: { paused?: boolean }) => !x.paused)
    if (!list) return
    if (!b) { setNone(true); return }
    const o = await fetch(`/api/business/${b.id}/overview`, { cache: "no-store" }).then((r) => (r.ok ? r.json() : null)).catch(() => null)
    if (o) { setNone(false); setOv(o) }
  }, [])

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch on mount; state is set after the await
    void load()
  }, [load])

  const save = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!ov || busy) return
    const amount = Number(sales.replace(/[^\d.]/g, ""))
    if (!amount) { setError("Enter today's total in rupees."); return }
    setBusy(true); setError(null)
    const r = await fetch(`/api/business/${ov.business.id}/days`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sales: amount, ...(bills ? { bills: Number(bills) } : {}) }),
    }).catch(() => null)
    setBusy(false)
    if (!r?.ok) { setError("Couldn't save that. Try again."); return }
    setOpen(false); setSales(""); setBills("")
    await load()
  }

  if (none) {
    return (
      <Link href="/business" className="h-shop-card h-shop-setup" data-testid="shop-setup">
        <i className="ti ti-building-store" style={{ fontSize: 26, color: "var(--brand)" }} aria-hidden />
        <span style={{ flex: 1 }}>
          <b style={{ display: "block", fontSize: 17 }}>Set up your shop</b>
          <span className="h-muted" style={{ fontSize: 15 }}>Then tell Hangul each day&apos;s sales and see tomorrow coming.</span>
        </span>
        <i className="ti ti-chevron-right h-muted" aria-hidden />
      </Link>
    )
  }
  if (!ov) return null

  const byDay = new Map(ov.days.map((d) => [d.day, d]))
  const today = byDay.get(ov.today)
  const yesterday = byDay.get(shift(ov.today, -1))
  const lastWeek = byDay.get(shift(ov.today, -7))
  const be = ov.plan?.breakeven ?? null
  const change = today && !today.closed && lastWeek && !lastWeek.closed && lastWeek.sales > 0
    ? Math.round((today.sales / lastWeek.sales - 1) * 100) : null
  const f = ov.forecast
  const slow = Boolean(ov.slow?.slow)

  return (
    <>
      <section className="h-shop-card h-shop-sales" data-testid="shop-sales" aria-label="Today's sales">
        <div className="h-shop-label">Today&apos;s sales · {ov.business.name}</div>
        {today && !today.closed ? (
          <>
            <div style={{ display: "flex", alignItems: "baseline", gap: 10, flexWrap: "wrap" }}>
              <span className="h-display h-shop-big">{rs(today.sales)}</span>
              {today.bills ? <span style={{ fontSize: 17 }}>{today.bills} bills</span> : null}
            </div>
            <div style={{ display: "flex", gap: 14, flexWrap: "wrap", fontSize: 16, fontWeight: 600 }}>
              {change !== null && (
                <span style={{ color: change >= 0 ? "var(--up)" : "var(--down)" }}>
                  {change >= 0 ? "↑" : "↓"} {Math.abs(change)}% vs last {weekday(ov.today)}
                </span>
              )}
              {be ? <span>{rs(Math.abs(today.sales - be))} {today.sales >= be ? "over" : "under"} break-even</span> : null}
            </div>
          </>
        ) : today?.closed ? (
          <div className="h-display h-shop-big" style={{ fontSize: 30 }}>Closed today</div>
        ) : (
          <>
            <div className="h-display h-shop-big" style={{ fontSize: 30 }}>Not logged yet</div>
            <div className="h-muted" style={{ fontSize: 16 }}>
              {yesterday && !yesterday.closed ? `Yesterday: ${rs(yesterday.sales)}${yesterday.bills ? ` · ${yesterday.bills} bills` : ""}` : "Log it when you close."}
            </div>
          </>
        )}
        {/* one button: floating above the tab bar on phones, inside this card on wider screens */}
        {!open && (
          <button type="button" className="h-shop-fab" onClick={() => setOpen(true)} data-testid="log-sales-fab">
            <i className="ti ti-cash" style={{ fontSize: 22 }} aria-hidden /> {today && !today.closed ? "Update sales" : "Log sales"}
          </button>
        )}
      </section>

      {ov.access.forecast && f && (
        <Link href={slow ? "/business#ideas" : "/business"} className={`h-shop-card h-shop-tomorrow${slow ? " is-slow" : ""}`} data-testid="shop-tomorrow">
          <i className={`ti ti-${slow ? "cloud-rain" : "calendar-event"}`} aria-hidden
            style={{ fontSize: 24, color: slow ? "var(--brand)" : "var(--fg)", flexShrink: 0 }} />
          <span style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column" }}>
            {f.status === "ready" && f.value != null ? (
              <>
                <span style={{ fontSize: 15, fontWeight: 700, color: slow ? "var(--down)" : "var(--muted)" }}>
                  {slow ? "Tomorrow looks slow · ↓" : `Tomorrow, ${weekday(ov.tomorrow)}`}
                </span>
                <span style={{ fontSize: 18, fontWeight: 700 }}>
                  About {rs(f.value)}{slow && be ? ", under break-even" : ""}
                </span>
                <span className="h-muted" style={{ fontSize: 15 }}>
                  {slow ? "An offer idea is ready." : f.low != null && f.high != null ? `Likely ${rs(f.low)} – ${rs(f.high)}` : ""}
                </span>
              </>
            ) : f.status === "learning" ? (
              <>
                <span style={{ fontSize: 15, fontWeight: 700 }} className="h-muted">Tomorrow</span>
                <span style={{ fontSize: 17, fontWeight: 600 }}>{f.days_needed} more days of sales and I can forecast it</span>
              </>
            ) : (
              <span style={{ fontSize: 17, fontWeight: 600 }}>Closed tomorrow</span>
            )}
          </span>
          <i className="ti ti-chevron-right h-muted" aria-hidden />
        </Link>
      )}

      {open && (
        <form className="h-shop-card h-shop-log" onSubmit={save} data-testid="log-sales-form">
          <b style={{ fontSize: 17 }}>Today&apos;s sales</b>
          <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 3fr) minmax(0, 2fr)", gap: 10 }}>
            <label className="h-shop-field">Total (₹)
              <input className="h-input" inputMode="decimal" autoFocus value={sales} onChange={(e) => setSales(e.target.value)}
                placeholder="16,400" data-testid="log-sales-amount" />
            </label>
            <label className="h-shop-field">Bills (optional)
              <input className="h-input" inputMode="numeric" value={bills} onChange={(e) => setBills(e.target.value.replace(/\D/g, ""))}
                placeholder="52" data-testid="log-sales-bills" />
            </label>
          </div>
          {error && <span role="alert" style={{ color: "var(--err)", fontSize: 14 }}>{error}</span>}
          <div style={{ display: "flex", gap: 10 }}>
            <button className="h-btn-solid" type="submit" disabled={busy} style={{ flex: 1 }} data-testid="log-sales-save">{busy ? "Saving…" : "Save"}</button>
            <Link href="/chat?voice=1" className="h-btn-outline" style={{ textDecoration: "none" }}>
              <i className="ti ti-microphone" aria-hidden /> Say it
            </Link>
            <button className="h-btn-outline" type="button" onClick={() => { setOpen(false); setError(null) }}>Cancel</button>
          </div>
        </form>
      )}

    </>
  )
}
