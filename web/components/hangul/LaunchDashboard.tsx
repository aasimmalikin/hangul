"use client"

import Link from "next/link"
import { useCallback, useEffect, useRef, useState } from "react"
import { BreakEvenChart, StartupBars } from "@/components/hangul/LaunchCharts"
import { CATEGORIES, isRefusal, launchApi, rupees, type Item, type Patch, type Plan } from "@/lib/launch"

/**
 * One launch plan: the numbers up top, the assumptions to play with, the
 * break-even and start-up charts, scenarios, then the checklist by category
 * (each item editable, with its sellers and where its price came from),
 * industry figures and nearby suppliers. Every number is the backend's
 * (`launch/economics.py`); edits are saved after a short pause and the
 * numbers come back recomputed. While live prices are being searched the page
 * polls and fills in as they arrive.
 */

const STAGE: Record<string, string> = {
  prices: "Finding prices and sellers", benchmarks: "Looking up industry figures", suppliers: "Finding suppliers near you",
}
const DISCLAIMER = "These are estimates to plan with, not financial advice. Check quotes with sellers before you spend."

function NumberField({ value, onCommit, step = 1, min = 0, max, suffix, label, testId, width = 110 }: {
  value: number; onCommit: (v: number) => void; step?: number; min?: number; max?: number; suffix?: string
  label: string; testId?: string; width?: number
}) {
  const [draft, setDraft] = useState<string | null>(null)
  const commit = () => {
    if (draft === null) return
    const v = Number(draft.replace(/[,₹\s]/g, ""))
    setDraft(null)
    if (Number.isFinite(v) && v >= min && (max === undefined || v <= max) && v !== value) onCommit(v)
  }
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
      <input className="h-input h-launch-num" inputMode="decimal" aria-label={label} data-testid={testId} style={{ width }}
        value={draft ?? String(value)} step={step}
        onChange={(ev) => setDraft(ev.target.value)} onBlur={commit}
        onKeyDown={(ev) => { if (ev.key === "Enter") (ev.target as HTMLInputElement).blur() }} />
      {suffix && <span className="h-muted" style={{ fontSize: 12 }}>{suffix}</span>}
    </span>
  )
}

function Tile({ label, value, sub, hero, testId, tone }: { label: string; value: string; sub?: string; hero?: boolean; testId: string; tone?: "ok" | "warn" }) {
  return (
    <div className={`h-launch-tile${hero ? " h-launch-tile-hero" : ""}`} data-testid={testId}>
      <span className="h-launch-tile-label">{label}</span>
      <span className="h-launch-tile-value">{value}</span>
      {sub && <span className="h-launch-tile-sub" data-tone={tone}>{sub}</span>}
    </div>
  )
}

function StatusBadge({ it }: { it: Item }) {
  if (it.status === "sourced") return <span className="h-badge" data-tone="ok" title="Checked against the sellers' pages">Sourced</span>
  if (it.status === "user") return <span className="h-badge" data-tone="brand">Your number</span>
  return <span className="h-badge" title="Hangul's rough range; not checked against a seller">Estimate</span>
}

function ItemRow({ it, onEdit, onRefresh, canRefresh, busy }: {
  it: Item; onEdit: (key: string, e: { amount?: number; qty?: number; include?: boolean }) => void
  onRefresh: (key: string) => void; canRefresh: boolean; busy: boolean
}) {
  return (
    <div className="h-launch-item" data-testid={`launch-item-${it.key}`} data-include={it.include}>
      <label className="h-launch-item-name">
        <input type="checkbox" checked={it.include} onChange={(ev) => onEdit(it.key, { include: ev.target.checked })}
          aria-label={`Include ${it.name}`} data-testid={`launch-include-${it.key}`} />
        <span>
          <b>{it.name}{it.monthly ? <span className="h-muted" style={{ fontWeight: 400 }}> · monthly</span> : null}</b>
          {it.why && <small>{it.why}</small>}
        </span>
      </label>
      <div className="h-launch-item-nums">
        <NumberField label={`Quantity of ${it.name}`} value={it.qty} max={1000} width={56} onCommit={(v) => onEdit(it.key, { qty: Math.round(v) })} />
        <span className="h-muted">×</span>
        <NumberField label={`Price of ${it.name}`} value={it.amount} max={1e9} width={104} testId={`launch-amount-${it.key}`}
          onCommit={(v) => onEdit(it.key, { amount: v })} />
        <span className="h-launch-item-total">{it.include ? rupees(it.amount * it.qty) : "—"}</span>
      </div>
      <div className="h-launch-item-meta">
        <StatusBadge it={it} />
        <span className="h-muted">{it.low === it.high ? rupees(it.low) : `${rupees(it.low)}–${rupees(it.high)}`}</span>
        {it.sellers.map((s) => (
          <a key={s.url + s.price} href={s.url} target="_blank" rel="noopener noreferrer nofollow" className="h-launch-seller" title={s.quote}>
            {s.seller} · {rupees(s.price)}
          </a>
        ))}
        {it.checked_at && it.status !== "estimate" && <span className="h-muted">checked {new Date(it.checked_at).toLocaleDateString()}</span>}
        {it.search && canRefresh && (
          <button className="h-btn-ghost" style={{ fontSize: 12, padding: "2px 8px" }} disabled={busy}
            onClick={() => onRefresh(it.key)} data-testid={`launch-refresh-${it.key}`}>
            <i className="ti ti-refresh" /> Re-check price
          </button>
        )}
      </div>
    </div>
  )
}

export function LaunchDashboard({ initial, unit }: { initial: Plan; unit: string }) {
  const [plan, setPlan] = useState<Plan>(initial)
  const [notice, setNotice] = useState<{ text: string; planNeeded?: string | null } | null>(null)
  const pending = useRef<Patch>({})
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const sourcing = plan.status === "sourcing"

  // poll while the background search runs
  useEffect(() => {
    if (!sourcing) return
    const t = setInterval(async () => {
      const r = await launchApi.get(plan.id)
      if (!isRefusal(r)) setPlan(r)
    }, 3000)
    return () => clearInterval(t)
  }, [sourcing, plan.id])

  const flush = useCallback(async () => {
    const body = pending.current
    pending.current = {}
    if (!Object.keys(body).length) return
    const r = await launchApi.patch(plan.id, body)
    if (isRefusal(r)) setNotice({ text: r.detail })
    else setPlan(r)
  }, [plan.id])

  const queue = useCallback((p: Patch) => {
    const cur = pending.current
    pending.current = {
      ...cur, ...p,
      variable: p.variable ? { ...cur.variable, ...p.variable } : cur.variable,
      items: p.items ? Object.fromEntries(Object.entries({ ...cur.items }).concat(
        Object.entries(p.items).map(([k, v]) => [k, { ...cur.items?.[k], ...v }]))) : cur.items,
    }
    if (timer.current) clearTimeout(timer.current)
    timer.current = setTimeout(() => void flush(), 500)
  }, [flush])

  // show an item edit at once (the numbers follow from the server)
  const editItem = (key: string, e: { amount?: number; qty?: number; include?: boolean }) => {
    setPlan((p) => ({ ...p, items: p.items.map((it) => it.key === key ? { ...it, ...e, ...(e.amount !== undefined ? { status: "user" as const } : {}) } : it) }))
    queue({ items: { [key]: e } })
  }

  const source = async () => {
    setNotice(null)
    const r = await launchApi.source(plan.id)
    if (isRefusal(r)) setNotice({ text: r.detail, planNeeded: r.planNeeded })
    else setPlan(r)
  }
  const refresh = async (key: string) => {
    setNotice(null)
    const r = await launchApi.refresh(plan.id, key)
    if (isRefusal(r)) setNotice({ text: r.detail, planNeeded: r.planNeeded })
    else setPlan(r)
  }

  const e = plan.economics
  const a = plan.assumptions
  const gap = e.budget_gap
  return (
    <div className="h-launch" data-testid="launch-dashboard" data-status={plan.status}>
      <div className="h-studio-hero">
        <div>
          <h1 data-testid="launch-title">{plan.title}</h1>
          <p>
            {plan.sourced ? "Prices searched live, checked against each seller's page." : "Hangul's starting estimates."} {DISCLAIMER}
          </p>
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <a className="h-btn-ghost" href={`/api/launch/${plan.id}/export?format=pdf`} data-testid="launch-export-pdf" style={{ textDecoration: "none", gap: 6 }}>
            <i className="ti ti-file-type-pdf" /> PDF
          </a>
          <a className="h-btn-ghost" href={`/api/launch/${plan.id}/export?format=xlsx`} data-testid="launch-export-xlsx" style={{ textDecoration: "none", gap: 6 }}>
            <i className="ti ti-file-spreadsheet" /> Excel
          </a>
        </div>
      </div>

      {sourcing && (
        <div className="h-launch-banner" role="status" data-testid="launch-progress">
          <span className="h-launch-spinner" aria-hidden />
          <span>
            <b>{STAGE[plan.progress.stage ?? "prices"] ?? "Working"}</b>
            {plan.progress.stage === "prices" && plan.progress.total ? ` · ${plan.progress.done ?? 0} of ${plan.progress.total} items` : ""}
            <span className="h-muted"> — this page fills in by itself; you can leave and come back.</span>
          </span>
        </div>
      )}
      {plan.status === "failed" && (
        <div className="h-launch-banner" data-tone="warn" role="alert" data-testid="launch-failed">
          <span>{plan.error || "The search stopped."}</span>
          <button className="h-btn-solid" style={{ marginLeft: "auto" }} onClick={() => void source()}>Try again</button>
        </div>
      )}
      {!plan.sourced && plan.status === "ready" && (
        <div className="h-launch-banner" data-testid="launch-estimates">
          <i className="ti ti-world-search" style={{ fontSize: 18 }} />
          <span>Want real prices? Hangul can search sellers for each item, look up industry figures and find suppliers near {plan.city}.</span>
          <button className="h-btn-solid" style={{ marginLeft: "auto" }} onClick={() => void source()} data-testid="launch-source">Search live prices</button>
        </div>
      )}
      {notice && (
        <div className="h-launch-banner" data-tone="warn" role="alert" data-testid="launch-notice">
          <span>{notice.text}</span>
          {notice.planNeeded && (
            <Link className="h-btn-solid" href={`/billing?upgrade=${notice.planNeeded}`} style={{ marginLeft: "auto", textDecoration: "none" }}>
              See {notice.planNeeded === "pro" ? "Pro" : "Plus"}
            </Link>
          )}
        </div>
      )}

      <section className="h-launch-tiles">
        <Tile hero label="Start-up cost" value={rupees(e.startup_total)} testId="launch-startup"
          sub={gap === null ? `incl. ${e.working_capital_months} months of running costs`
            : gap >= 0 ? `${rupees(gap)} under your budget` : `${rupees(-gap)} over your budget`}
          tone={gap === null ? undefined : gap >= 0 ? "ok" : "warn"} />
        <Tile label="Monthly profit" value={rupees(e.profit)} testId="launch-profit" tone={e.profit >= 0 ? "ok" : "warn"}
          sub={e.margin === null ? undefined : `${Math.round(e.margin * 100)}% of ${rupees(e.revenue, true)} revenue`} />
        <Tile label="Break-even" value={e.breakeven_per_day === null ? "—" : `${e.breakeven_per_day} ${unit}s/day`} testId="launch-breakeven-tile"
          sub={`you plan ${e.units_per_day} a day`} tone={e.breakeven_per_day !== null && e.breakeven_per_day <= e.units_per_day ? "ok" : "warn"} />
        <Tile label="Payback" value={e.payback_months === null ? "Not yet" : `${e.payback_months} months`} testId="launch-payback"
          sub={e.payback_months === null ? "at these numbers it doesn't pay back" : "to earn back the start-up cost"} />
      </section>

      <section className="h-launch-grid">
        <div className="h-studio-panel">
          <div className="h-studio-step">Your assumptions</div>
          <div className="h-launch-assume">
            <label>Average sale<NumberField label="Average sale in rupees" value={a.price} max={1e7} testId="launch-price"
              onCommit={(v) => queue({ price: v })} suffix={`₹ per ${unit}`} /></label>
            <label>Sales a day<NumberField label={`${unit}s a day`} value={a.units_per_day} max={1e5} testId="launch-units"
              onCommit={(v) => queue({ units_per_day: v })} suffix={`${unit}s`} /></label>
            <label>Days open a month<NumberField label="Days open a month" value={a.days_per_month} min={1} max={31} width={64}
              onCommit={(v) => queue({ days_per_month: v })} /></label>
            <label>Cushion for a slow start<NumberField label="Months of running costs to keep" value={a.working_capital_months} max={12} width={64}
              onCommit={(v) => queue({ working_capital_months: v })} suffix="months" /></label>
          </div>
          <div className="h-studio-section-title" style={{ margin: "4px 0 0" }}>Costs of each sale</div>
          <div className="h-launch-assume">
            {a.variable.map((v) => (
              <label key={v.key}>{v.label}<NumberField label={`${v.label} as % of the price`} value={Math.round(v.pct * 1000) / 10} max={99} width={64}
                onCommit={(n) => queue({ variable: { [v.key]: n / 100 } })} suffix="%" testId={`launch-var-${v.key}`} /></label>
            ))}
          </div>
          <table className="h-launch-table" data-testid="launch-scenarios">
            <thead><tr><th /><th>Sales/day</th><th>Profit/month</th><th>Payback</th></tr></thead>
            <tbody>
              {(["worst", "likely", "best"] as const).map((k) => {
                const s = e.scenarios[k]
                return (
                  <tr key={k}>
                    <td>{k === "worst" ? "Slow (−30%)" : k === "likely" ? "Your plan" : "Busy (+30%)"}</td>
                    <td>{Math.round(s.units_per_day * 10) / 10}</td>
                    <td>{rupees(s.profit)}</td>
                    <td>{s.payback_months ? `${s.payback_months} mo` : "—"}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
        <div className="h-studio-panel">
          <div className="h-studio-step">When do you break even?</div>
          <BreakEvenChart e={e} unit={unit} />
          <div className="h-studio-step" style={{ marginTop: 6 }}>Where the start-up money goes</div>
          <StartupBars items={plan.items} e={e} />
        </div>
      </section>

      <section className="h-studio-panel" data-testid="launch-checklist">
        <div className="h-studio-step">What you&apos;ll need</div>
        {CATEGORIES.map(([key, label, icon]) => {
          const rows = plan.items.filter((it) => it.category === key)
          if (!rows.length) return null
          const total = rows.reduce((s, it) => s + (it.include ? it.amount * it.qty : 0), 0)
          return (
            <div key={key} className="h-launch-cat">
              <div className="h-launch-cat-head">
                <i className={`ti ti-${icon}`} /> {label}
                <span className="h-muted" style={{ marginLeft: "auto", fontVariantNumeric: "tabular-nums" }}>{rupees(total)}</span>
              </div>
              {rows.map((it) => (
                <ItemRow key={it.key} it={it} onEdit={editItem} onRefresh={(k) => void refresh(k)}
                  canRefresh={plan.sourced} busy={sourcing} />
              ))}
            </div>
          )
        })}
      </section>

      <section className="h-launch-grid">
        <div className="h-studio-panel" data-testid="launch-benchmarks">
          <div className="h-studio-step">How businesses like this usually do</div>
          {plan.benchmarks.map((b) => (
            <div key={b.key} className="h-launch-bench">
              <span>{b.label}</span>
              <b>{b.value}</b>
              {b.source
                ? <a href={b.source.url} target="_blank" rel="noopener noreferrer nofollow" title={b.quote} className="h-launch-seller">
                    {(() => { try { return new URL(b.source.url).hostname.replace(/^www\./, "") } catch { return "source" } })()}
                  </a>
                : <span className="h-badge">Estimate</span>}
            </div>
          ))}
        </div>
        <div className="h-studio-panel" data-testid="launch-suppliers">
          <div className="h-studio-step">Suppliers near {plan.city}</div>
          {plan.suppliers.length === 0 && (
            <span className="h-muted" style={{ fontSize: 13 }}>
              {plan.sourced ? (sourcing ? "Looking…" : "None found on the map. Ask around locally, or search Google Maps.") : "Search live prices to find suppliers on the map."}
            </span>
          )}
          {plan.suppliers.map((s) => (
            <div key={s.query} className="h-launch-supplier">
              <b style={{ textTransform: "capitalize" }}>{s.query}</b>
              {s.places.slice(0, 4).map((p) => (
                <span key={p.name + p.address} className="h-muted" style={{ fontSize: 13 }}>
                  {p.link ? <a href={p.link} target="_blank" rel="noopener noreferrer nofollow">{p.name}</a> : p.name}
                  {p.address ? ` · ${p.address.split(",").slice(1, 3).join(",").trim()}` : ""}
                </span>
              ))}
              <a href={s.search_link} target="_blank" rel="noopener noreferrer nofollow" style={{ fontSize: 12 }}>More on Google Maps →</a>
            </div>
          ))}
          <span className="h-muted" style={{ fontSize: 12 }}>From OpenStreetMap: no ratings or opening hours. Call before you go.</span>
        </div>
      </section>
    </div>
  )
}
