"use client"

import Link from "next/link"
import { useEffect, useRef, useState } from "react"
import { useRouter } from "next/navigation"
import { SalesChart } from "@/components/hangul/BusinessChart"
import { rupees } from "@/lib/launch"
import { businessApi, dayName, isRefusal, shortDate, type Business, type Imported, type Listing, type Overview } from "@/lib/business"

/**
 * How's business: log today, see the week, tomorrow's forecast with its range
 * and how accurate it has been, and on a slow day ideas that open Brand Studio
 * with the post ready. What shows follows the plan (`overview.access`):
 * Free logs and sees the week, Plus adds the forecast and one idea a week, Pro
 * adds why and an idea for every slow day.
 */

const KIND_ICON: Record<string, string> = {
  cloud_kitchen: "chef-hat", cafe: "coffee", retail_shop: "building-store", salon: "scissors", d2c_brand: "package", other: "briefcase",
}
// a change always carries an arrow, never colour alone (direction A)
const pct = (v: number) => `${v >= 0 ? "↑" : "↓"} ${Math.abs(Math.round(v * 100))}%`

function Locked({ feature, plan }: { feature: string; plan: string }) {
  return (
    <div className="h-biz-locked" data-testid={`biz-locked-${plan}`}>
      <i className="ti ti-lock" />
      <span>{feature} is part of {plan === "pro" ? "Pro" : "Plus"}.</span>
      <Link href={`/billing?upgrade=${plan}`} className="h-btn-ghost" style={{ textDecoration: "none", fontSize: 13 }}>See {plan === "pro" ? "Pro" : "Plus"}</Link>
    </div>
  )
}

export function BusinessSetup({ listing, onSaved }: { listing: Listing; onSaved: (b: Business) => void }) {
  const [name, setName] = useState("")
  const [kind, setKind] = useState("")
  const [city, setCity] = useState("")
  const [plans, setPlans] = useState<Array<{ id: number; title: string }>>([])
  const [brands, setBrands] = useState<Array<{ id: number; name: string }>>([])
  const [plan, setPlan] = useState("")
  const [brand, setBrand] = useState("")
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    void fetch("/api/launch", { cache: "no-store" }).then((r) => (r.ok ? r.json() : [])).then((x) => setPlans(Array.isArray(x) ? x : [])).catch(() => {})
    void fetch("/api/brands", { cache: "no-store" }).then((r) => (r.ok ? r.json() : null)).then((x) => setBrands(x?.brands ?? [])).catch(() => {})
  }, [])
  const save = async () => {
    setError(null)
    const r = await businessApi.create({ name: name.trim(), kind: kind || "other", city: city.trim(),
      launch_plan_id: plan ? Number(plan) : null, brand_id: brand ? Number(brand) : null })
    if (isRefusal(r)) setError(r.detail)
    else onSaved(r)
  }
  return (
    <section className="h-studio-panel" data-testid="biz-setup" style={{ gap: 14 }}>
      <div className="h-studio-step"><b>1</b> Your business</div>
      <div className="h-launch-row">
        <label className="h-field"><span>Name</span>
          <input className="h-input" value={name} onChange={(e) => setName(e.target.value)} placeholder="Chinar Café" maxLength={80} data-testid="biz-name" />
        </label>
        <label className="h-field"><span>City</span>
          <input className="h-input" value={city} onChange={(e) => setCity(e.target.value)} placeholder="Srinagar" maxLength={80} data-testid="biz-city" />
          <small>For the weather: rain changes sales more than people think.</small>
        </label>
      </div>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        {listing.kinds.map((k) => (
          <button key={k.key} className="h-size-chip" aria-pressed={kind === k.key} onClick={() => setKind(k.key)} data-testid={`biz-kind-${k.key}`}>
            <i className={`ti ti-${KIND_ICON[k.key] ?? "briefcase"}`} style={{ marginRight: 6 }} />{k.label}
          </button>
        ))}
      </div>
      <div className="h-studio-step"><b>2</b> Connect what you already made <small className="h-muted" style={{ fontWeight: 400 }}>(optional)</small></div>
      <div className="h-launch-row">
        <label className="h-field"><span>Launch plan</span>
          <select className="h-input" value={plan} onChange={(e) => setPlan(e.target.value)} data-testid="biz-plan">
            <option value="">None</option>
            {plans.map((p) => <option key={p.id} value={p.id}>{p.title}</option>)}
          </select>
          <small>Its break-even and margins make the forecast and offers smarter.</small>
        </label>
        <label className="h-field"><span>Brand</span>
          <select className="h-input" value={brand} onChange={(e) => setBrand(e.target.value)} data-testid="biz-brand">
            <option value="">None</option>
            {brands.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
          </select>
          <small>Slow-day posts come out in your colours and logo.</small>
        </label>
      </div>
      {error && <span role="alert" style={{ color: "var(--err)", fontSize: 13 }}>{error}</span>}
      <button className="h-btn-solid" style={{ alignSelf: "flex-start" }} disabled={!name.trim()} onClick={() => void save()} data-testid="biz-save">
        Start tracking
      </button>
    </section>
  )
}

function LogToday({ ov, onSaved }: { ov: Overview; onSaved: () => void }) {
  const today = ov.days.find((d) => d.day === ov.today)
  const [sales, setSales] = useState("")
  const [bills, setBills] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const save = async (closed = false) => {
    const n = Number(sales.replace(/[,₹\s]/g, ""))
    if (!closed && (!Number.isFinite(n) || n < 0 || !sales.trim())) { setError("Type today's total sales in rupees."); return }
    setBusy(true)
    setError(null)
    const r = await businessApi.log(ov.business.id, closed ? { closed: true } : { sales: n, bills: bills.trim() ? Math.round(Number(bills)) : null })
    setBusy(false)
    if (isRefusal(r)) setError(r.detail)
    else { setSales(""); setBills(""); onSaved() }
  }
  return (
    <section className="h-studio-panel" data-testid="biz-log">
      <div className="h-studio-step">Today, {shortDate(ov.today)}</div>
      {today && (
        <div className="h-biz-logged" data-testid="biz-logged">
          <i className="ti ti-circle-check" />
          {today.closed ? "Closed today." : <>Logged {rupees(today.sales)}{today.bills ? ` · ${today.bills} bills` : ""}.</>}
          <span className="h-muted">Type again to replace it.</span>
        </div>
      )}
      <div className="h-launch-row">
        <label className="h-field"><span>Total sales (₹)</span>
          <input className="h-input" inputMode="numeric" value={sales} onChange={(e) => setSales(e.target.value)} placeholder="16,400" data-testid="biz-sales"
            onKeyDown={(e) => { if (e.key === "Enter") void save() }} />
        </label>
        <label className="h-field"><span>Bills <small>(optional)</small></span>
          <input className="h-input" inputMode="numeric" value={bills} onChange={(e) => setBills(e.target.value)} placeholder="52" data-testid="biz-bills"
            onKeyDown={(e) => { if (e.key === "Enter") void save() }} />
        </label>
      </div>
      {error && <span role="alert" style={{ color: "var(--err)", fontSize: 13 }}>{error}</span>}
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <button className="h-btn-solid" disabled={busy} onClick={() => void save()} data-testid="biz-log-save">Save today</button>
        <button className="h-btn-ghost" disabled={busy} onClick={() => void save(true)}>Closed today</button>
      </div>
      <span className="h-muted" style={{ fontSize: 12 }}>
        Or just tell Hangul in chat or on WhatsApp: <i>&ldquo;today 52 bills, 16,400&rdquo;</i>.
      </span>
      <ImportSales businessId={ov.business.id} onDone={onSaved} />
    </section>
  )
}

function ImportSales({ businessId, onDone }: { businessId: number; onDone: () => void }) {
  const input = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<Imported | null>(null)
  const [cols, setCols] = useState<{ date_col: string; amount_col: string }>({ date_col: "", amount_col: "" })
  const [msg, setMsg] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const look = async (f: File, c = cols) => {
    setBusy(true); setMsg(null)
    const r = await businessApi.importFile(businessId, f, { preview: true, ...c })
    setBusy(false)
    if (isRefusal(r)) { setPreview(null); setMsg(r.detail) } else setPreview(r)
  }
  const save = async () => {
    if (!file) return
    setBusy(true)
    const r = await businessApi.importFile(businessId, file, { ...cols })
    setBusy(false)
    if (isRefusal(r)) { setMsg(r.detail); return }
    setMsg(`Added ${r.saved?.added ?? 0} days${r.saved?.kept ? ` (kept ${r.saved.kept} you'd already logged)` : ""}.`)
    setPreview(null); setFile(null); onDone()
  }
  return (
    <div className="h-biz-import">
      <button className="h-btn-ghost" style={{ fontSize: 13, gap: 6 }} onClick={() => input.current?.click()} data-testid="biz-import">
        <i className="ti ti-file-spreadsheet" /> Import past sales
      </button>
      <span className="h-muted" style={{ fontSize: 12 }}>Excel or CSV from Vyapar, myBillBook, Tally, Petpooja, or a PhonePe / Paytm statement.</span>
      <input ref={input} type="file" accept=".xlsx,.xls,.csv" hidden data-testid="biz-import-file"
        onChange={(e) => { const f = e.target.files?.[0]; if (f) { setFile(f); void look(f) } e.target.value = "" }} />
      {preview && (
        <div className="h-biz-preview" data-testid="biz-import-preview">
          <b>{preview.days.length} days found, {preview.from && shortDate(preview.from)} to {preview.to && shortDate(preview.to)}: {rupees(preview.total)}</b>
          <span className="h-muted" style={{ fontSize: 12 }}>Dates from “{preview.date_col}”, amounts from “{preview.amount_col}”. {preview.notes.join(" ")}</span>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
            <select className="h-input" style={{ width: "auto" }} value={cols.amount_col || preview.amount_col} aria-label="Amount column"
              onChange={(e) => { const c = { ...cols, amount_col: e.target.value }; setCols(c); if (file) void look(file, c) }}>
              {preview.columns.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
            <button className="h-btn-solid" disabled={busy} onClick={() => void save()} data-testid="biz-import-save">Add these days</button>
            <button className="h-btn-ghost" onClick={() => { setPreview(null); setFile(null) }}>Cancel</button>
          </div>
        </div>
      )}
      {msg && <span className="h-muted" role="status" style={{ fontSize: 13 }} data-testid="biz-import-msg">{msg}</span>}
    </div>
  )
}

function Tomorrow({ ov }: { ov: Overview }) {
  const f = ov.forecast
  const locked = ov.locked.find((l) => l.plan === "plus")
  return (
    <section className="h-studio-panel h-biz-tomorrow" data-testid="biz-tomorrow" data-slow={ov.slow?.slow ? "true" : "false"}>
      <div className="h-studio-step" style={{ justifyContent: "space-between" }}>
        <span>Tomorrow, {dayName(ov.tomorrow)}</span>
        {ov.slow?.slow && <span className="h-badge" data-tone="warn" data-testid="biz-slow"><i className="ti ti-trending-down" /> Looks slow</span>}
      </div>
      {locked ? (
        <>
          <p className="h-muted" style={{ margin: 0, fontSize: 14 }}>
            Hangul can forecast tomorrow&apos;s sales from your history, the weather and festivals, and warn you about slow days.
          </p>
          <Locked feature="Tomorrow's sales forecast" plan="plus" />
        </>
      ) : f?.status === "learning" ? (
        <div data-testid="biz-learning">
          <p style={{ margin: "0 0 8px", fontSize: 14 }}>Hangul is learning your business: {f.days_logged} of 14 days logged.</p>
          <div className="h-biz-progress"><span style={{ width: `${Math.min(100, (f.days_logged / 14) * 100)}%` }} /></div>
          <p className="h-muted" style={{ fontSize: 12, margin: "8px 0 0" }}>Importing past sales gets you there today.</p>
        </div>
      ) : f?.status === "closed" ? (
        <p style={{ margin: 0 }}>You&apos;re closed tomorrow.</p>
      ) : f?.status === "ready" ? (
        <>
          <div className="h-biz-hero" data-testid="biz-forecast">
            <span className="h-biz-hero-value">{rupees(f.value)}</span>
            <span className="h-muted">likely {rupees(f.low)} – {rupees(f.high)}</span>
          </div>
          <div className="h-biz-meta">
            {f.typical ? <span>A usual {dayName(ov.tomorrow)}: {rupees(f.typical)}</span> : null}
            {ov.slow?.breakeven ? <span>Break-even: {rupees(ov.slow.breakeven)}</span> : null}
            {ov.weather_tomorrow?.rain_mm !== null && ov.weather_tomorrow ? <span><i className="ti ti-cloud-rain" /> {ov.weather_tomorrow.rain_mm} mm rain</span> : null}
            {ov.festival_tomorrow ? <span><i className="ti ti-sparkles" /> {ov.festival_tomorrow}</span> : null}
          </div>
          {f.reasons && f.reasons.length > 0 && (
            <div className="h-biz-reasons" data-testid="biz-reasons">
              {f.reasons.map((r) => (
                <span key={r.key} className="h-chip" data-tone={r.effect < 0 ? "down" : "up"}>
                  {r.label} <b>{pct(r.effect)}</b>
                </span>
              ))}
            </div>
          )}
          {ov.locked.some((l) => l.feature.startsWith("Why")) && <Locked feature="Why tomorrow looks this way" plan="pro" />}
          <span className="h-muted" style={{ fontSize: 12 }} data-testid="biz-accuracy">
            Based on {f.model_label}{f.accuracy !== null && f.accuracy !== undefined ? `. Over the last ${f.backtest_days} days Hangul was within ${Math.round(f.accuracy * 100)}% on average` : ""}.
            {" "}A forecast, not a promise.
          </span>
          {(f.notes ?? []).map((n) => <span key={n} className="h-muted" style={{ fontSize: 12 }}>{n}</span>)}
        </>
      ) : null}
    </section>
  )
}

function Ideas({ ov }: { ov: Overview }) {
  const router = useRouter()
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  if (!ov.slow?.slow) return null
  const make = async (key: string) => {
    setBusy(key); setError(null)
    const r = await businessApi.useIdea(ov.business.id, key)
    setBusy(null)
    if (isRefusal(r)) setError(r.detail)
    else router.push(r.studio_url)
  }
  return (
    <section className="h-studio-panel" id="ideas" data-testid="biz-ideas">
      <div className="h-studio-step">Make tomorrow busier</div>
      {ov.ideas.length === 0 && ov.locked.some((l) => l.plan === "pro") && (
        <p className="h-muted" style={{ margin: 0, fontSize: 14 }}>You&apos;ve used this week&apos;s idea.</p>
      )}
      <div className="h-biz-ideas">
        {ov.ideas.map((i) => (
          <article key={i.key} className="h-biz-idea" data-testid={`biz-idea-${i.key}`}>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <b>{i.title}</b>
              {i.discount > 0 && <span className="h-badge" data-tone="brand">{i.discount}% off</span>}
            </div>
            <span style={{ fontSize: 14 }}>{i.idea}</span>
            {i.margin_note && <span className="h-muted" style={{ fontSize: 12 }}><i className="ti ti-shield-check" /> {i.margin_note}{i.discount_cut ? " (Hangul lowered the discount to protect your margin.)" : ""}</span>}
            <span className="h-muted" style={{ fontSize: 12 }}>{i.share}</span>
            <button className="h-btn-solid" style={{ alignSelf: "flex-start", gap: 6 }} disabled={busy !== null} onClick={() => void make(i.key)} data-testid={`biz-make-${i.key}`}>
              <i className="ti ti-wand" /> {ov.business.brand_id ? "Make this post" : "Set up your brand to make it"}
            </button>
          </article>
        ))}
      </div>
      {ov.ideas_left !== null && ov.ideas.length > 0 && (
        <span className="h-muted" style={{ fontSize: 12 }}>{ov.ideas_left > 0 ? "Plus includes one idea a week." : "This week's idea."}</span>
      )}
      {(ov.access.ideas === "all" || ov.access.ideas === "weekly") && (
        <span className="h-muted" style={{ fontSize: 13 }} data-testid="biz-missions-link">
          <i className="ti ti-checklist" /> The evening before a slow day{ov.access.ideas === "weekly" ? " (once a week on Plus)" : ""}, Hangul makes the post and asks you once. <Link href="/missions">Slow days, handled</Link>
        </span>
      )}
      {ov.locked.some((l) => l.feature.startsWith("An idea")) && <Locked feature="An idea for every slow day" plan="pro" />}
      {error && <span role="alert" style={{ color: "var(--err)", fontSize: 13 }}>{error}</span>}
    </section>
  )
}

export function BusinessDashboard({ ov, onChange }: { ov: Overview; onChange: () => void }) {
  const w = ov.week
  const recent = [...ov.days].reverse().slice(0, 14)
  return (
    <div className="h-launch" data-testid="biz-dashboard">
      <section className="h-launch-tiles">
        <div className="h-launch-tile h-launch-tile-hero" data-testid="biz-week">
          <span className="h-launch-tile-label">This week so far</span>
          <span className="h-launch-tile-value">{rupees(w.total)}</span>
          <span className="h-launch-tile-sub" data-tone={w.change === null ? undefined : w.change >= 0 ? "ok" : "warn"}>
            {w.change === null ? `${w.days} day${w.days === 1 ? "" : "s"} logged` : `${pct(w.change)} on the same days last week`}
          </span>
        </div>
        <div className="h-launch-tile">
          <span className="h-launch-tile-label">Bills this week</span>
          <span className="h-launch-tile-value">{w.bills || "—"}</span>
          {ov.avg_bill ? <span className="h-launch-tile-sub">average bill {rupees(ov.avg_bill)}</span> : null}
        </div>
        <div className="h-launch-tile">
          <span className="h-launch-tile-label">Best day</span>
          <span className="h-launch-tile-value">{w.best ? dayName(w.best) : "—"}</span>
        </div>
        <div className="h-launch-tile">
          <span className="h-launch-tile-label">Break-even a day</span>
          <span className="h-launch-tile-value">{ov.plan.breakeven ? rupees(ov.plan.breakeven) : "—"}</span>
          <span className="h-launch-tile-sub">{ov.plan.plan_title ? `from “${ov.plan.plan_title}”` : <Link href="/launch">Link a launch plan</Link>}</span>
        </div>
      </section>
      <section className="h-launch-grid">
        <LogToday ov={ov} onSaved={onChange} />
        <div style={{ display: "flex", flexDirection: "column", gap: 16, minWidth: 0 }}>
          <Tomorrow ov={ov} />
          <Ideas ov={ov} />
        </div>
      </section>
      <section className="h-studio-panel">
        <div className="h-studio-step">The last six weeks</div>
        <SalesChart days={ov.days} expected={ov.expected ?? []} breakeven={ov.plan.breakeven} today={ov.today} />
        <table className="h-launch-table" data-testid="biz-days">
          <thead><tr><th>Day</th><th>Sales</th><th>Bills</th><th /></tr></thead>
          <tbody>
            {recent.map((d) => (
              <tr key={d.day}>
                <td>{shortDate(d.day)}{d.rain_mm !== null && d.rain_mm >= 2.5 ? " 🌧" : ""}</td>
                <td>{d.closed ? "Closed" : rupees(d.sales)}</td>
                <td>{d.bills ?? "—"}</td>
                <td style={{ textAlign: "right" }}>
                  <button className="h-btn-ghost" style={{ fontSize: 12, padding: "2px 6px" }} aria-label={`Remove ${d.day}`}
                    onClick={() => void businessApi.removeDay(ov.business.id, d.day).then(onChange)}><i className="ti ti-x" /></button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  )
}
