"use client"

import { useMemo, useRef, useState } from "react"
import { CATEGORIES, rupees, type Economics, type Item } from "@/lib/launch"

/**
 * The launch dashboard's two charts, plain SVG on the theme's `--viz-*`
 * tokens (validated pair, light and dark): break-even (revenue vs total costs
 * by sales a day, one axis) and the start-up cost by category (one series,
 * bars). Both have a hover read-out; the checklist below is the table view.
 */

function niceStep(max: number, ticks = 4): number {
  const raw = max / ticks
  const mag = 10 ** Math.floor(Math.log10(Math.max(raw, 1)))
  return ([1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? 10 * mag)
}

export function BreakEvenChart({ e, unit }: { e: Economics; unit: string }) {
  const W = 640, H = 260, L = 64, R = 74, T = 16, B = 34
  const pts = e.chart
  const xMax = pts[pts.length - 1]?.units_per_day || 1
  const yTop = Math.max(...pts.map((p) => Math.max(p.revenue, p.costs)), 1)
  const step = niceStep(yTop)
  const yMax = Math.ceil(yTop / step) * step
  const x = (u: number) => L + (u / xMax) * (W - L - R)
  const y = (v: number) => T + (1 - v / yMax) * (H - T - B)
  const line = (k: "revenue" | "costs") => pts.map((p, i) => `${i ? "L" : "M"}${x(p.units_per_day).toFixed(1)},${y(p[k]).toFixed(1)}`).join(" ")
  const ticks = Array.from({ length: Math.round(yMax / step) + 1 }, (_, i) => i * step)
  const xStep = niceStep(xMax, 5)
  const xTicks = Array.from({ length: Math.floor(xMax / xStep) + 1 }, (_, i) => i * xStep)
  const be = e.breakeven_per_day
  const last = pts[pts.length - 1]
  const labelsClash = last ? Math.abs(y(last.revenue) - y(last.costs)) < 16 : true
  const [hover, setHover] = useState<number | null>(null)
  const svg = useRef<SVGSVGElement>(null)

  const at = (u: number) => {
    const var_ = e.variable_share
    const rev = e.price * u * e.days_per_month
    return { u, revenue: rev, costs: e.fixed + rev * var_, profit: rev * (1 - var_) - e.fixed }
  }
  const onMove = (ev: React.PointerEvent) => {
    const r = svg.current?.getBoundingClientRect()
    if (!r) return
    const px = ((ev.clientX - r.left) / r.width) * W
    const u = Math.max(0, Math.min(xMax, ((px - L) / (W - L - R)) * xMax))
    setHover(Math.round(u * 10) / 10)
  }
  const h = hover === null ? null : at(hover)

  return (
    <figure className="h-launch-chart" data-testid="launch-breakeven" style={{ margin: 0 }}>
      <div className="h-launch-legend" aria-hidden>
        <span><i style={{ background: "var(--viz-1)" }} />Revenue</span>
        <span><i style={{ background: "var(--viz-2)" }} />Total costs</span>
      </div>
      <div style={{ position: "relative" }}>
        <svg ref={svg} viewBox={`0 0 ${W} ${H}`} width="100%" role="img" style={{ display: "block", touchAction: "pan-y" }}
          aria-label={`Break-even at ${be ?? "no"} ${unit}s a day: revenue and costs by ${unit}s a day`}
          onPointerMove={onMove} onPointerLeave={() => setHover(null)}>
          {ticks.map((t) => (
            <g key={t}>
              <line x1={L} x2={W - R} y1={y(t)} y2={y(t)} stroke="var(--viz-grid)" strokeWidth={1} />
              <text x={L - 8} y={y(t) + 4} textAnchor="end" className="h-launch-tick">{rupees(t, true)}</text>
            </g>
          ))}
          {xTicks.map((t) => (
            <text key={t} x={x(t)} y={H - B + 18} textAnchor="middle" className="h-launch-tick">{t}</text>
          ))}
          <text x={(L + W - R) / 2} y={H - 2} textAnchor="middle" className="h-launch-tick">{unit}s a day</text>
          {e.units_per_day > 0 && e.units_per_day <= xMax && (
            <g>
              <line x1={x(e.units_per_day)} x2={x(e.units_per_day)} y1={T} y2={H - B} stroke="var(--muted)" strokeWidth={1} />
              <text x={x(e.units_per_day) + 4} y={T + 10} className="h-launch-tick">your plan</text>
            </g>
          )}
          <path d={line("costs")} fill="none" stroke="var(--viz-2)" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />
          <path d={line("revenue")} fill="none" stroke="var(--viz-1)" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />
          {be !== null && be <= xMax && (
            <g data-testid="launch-breakeven-point">
              <circle cx={x(be)} cy={y(at(be).revenue)} r={5} fill="var(--fg)" stroke="var(--surface-solid)" strokeWidth={2} />
              <text x={x(be) + 8} y={y(at(be).revenue) + 16} className="h-launch-label">break-even · {be}/day</text>
            </g>
          )}
          {last && !labelsClash && (
            <>
              <circle cx={x(last.units_per_day)} cy={y(last.revenue)} r={4} fill="var(--viz-1)" stroke="var(--surface-solid)" strokeWidth={2} />
              <text x={x(last.units_per_day) + 8} y={y(last.revenue) + 4} className="h-launch-label">Revenue</text>
              <circle cx={x(last.units_per_day)} cy={y(last.costs)} r={4} fill="var(--viz-2)" stroke="var(--surface-solid)" strokeWidth={2} />
              <text x={x(last.units_per_day) + 8} y={y(last.costs) + 4} className="h-launch-label">Costs</text>
            </>
          )}
          {h && (
            <g pointerEvents="none">
              <line x1={x(h.u)} x2={x(h.u)} y1={T} y2={H - B} stroke="var(--fg)" strokeOpacity={0.35} strokeWidth={1} />
              <circle cx={x(h.u)} cy={y(h.revenue)} r={4} fill="var(--viz-1)" stroke="var(--surface-solid)" strokeWidth={2} />
              <circle cx={x(h.u)} cy={y(h.costs)} r={4} fill="var(--viz-2)" stroke="var(--surface-solid)" strokeWidth={2} />
            </g>
          )}
        </svg>
        {h && (
          <div className="h-launch-tip" role="status" style={{ left: `${(x(h.u) / W) * 100}%` }}>
            <b>{h.u} {unit}s a day</b>
            <span><i style={{ background: "var(--viz-1)" }} />Revenue {rupees(h.revenue)}</span>
            <span><i style={{ background: "var(--viz-2)" }} />Costs {rupees(h.costs)}</span>
            <span>{h.profit >= 0 ? "Profit" : "Loss"} {rupees(Math.abs(h.profit))} a month</span>
          </div>
        )}
      </div>
    </figure>
  )
}

/** Start-up cost by category: one-off items per category, plus the working capital. */
export function StartupBars({ items, e }: { items: Item[]; e: Economics }) {
  const rows = useMemo(() => {
    const out: Array<{ label: string; value: number }> = []
    for (const [key, label] of CATEGORIES) {
      const v = items.filter((it) => it.category === key && !it.monthly && it.include).reduce((s, it) => s + it.amount * it.qty, 0)
      if (v > 0) out.push({ label, value: v })
    }
    if (e.working_capital > 0) out.push({ label: `Running costs for ${e.working_capital_months} months`, value: e.working_capital })
    return out.sort((a, b) => b.value - a.value)
  }, [items, e.working_capital, e.working_capital_months])
  const max = Math.max(...rows.map((r) => r.value), 1)
  const [hover, setHover] = useState<string | null>(null)
  return (
    <div className="h-launch-bars" data-testid="launch-startup-bars">
      {rows.map((r) => (
        <div key={r.label} className="h-launch-bar-row" onPointerEnter={() => setHover(r.label)} onPointerLeave={() => setHover(null)}
          title={`${r.label}: ${rupees(r.value)} (${Math.round((r.value / e.startup_total) * 100)}% of the start-up cost)`}>
          <span className="h-launch-bar-label">{r.label}</span>
          <span className="h-launch-bar-track">
            <span className="h-launch-bar" style={{ width: `calc((100% - 72px) * ${Math.max(0.01, r.value / max)})`, opacity: hover && hover !== r.label ? 0.45 : 1 }} />
            <span className="h-launch-bar-value">{rupees(r.value, true)}</span>
          </span>
        </div>
      ))}
    </div>
  )
}
