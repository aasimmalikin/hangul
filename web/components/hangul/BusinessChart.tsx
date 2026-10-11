"use client"

import { useRef, useState } from "react"
import { rupees } from "@/lib/launch"
import { shortDate, type Day } from "@/lib/business"

/**
 * The last six weeks: what was sold (--viz-1) against what the forecast would
 * have said the day before (--viz-2), on one rupee axis, with break-even as a
 * muted rule. Days not logged leave a gap rather than a made-up line. Hover or
 * drag shows the day; the table under it is the accessible view.
 */
export function SalesChart({ days, expected, breakeven, today }: {
  days: Day[]; expected: Array<{ day: string; expected: number }>; breakeven: number | null | undefined; today: string
}) {
  const W = 760, H = 240, L = 58, R = 16, T = 14, B = 30
  const end = new Date(today + "T12:00:00")
  const dates = Array.from({ length: 42 }, (_, i) => {
    const d = new Date(end)
    d.setDate(d.getDate() - 41 + i)
    return d.toLocaleDateString("en-CA")
  })
  const byDay = new Map(days.map((d) => [d.day, d]))
  const exp = new Map(expected.map((e) => [e.day, e.expected]))
  const vals = dates.flatMap((d) => [byDay.get(d)?.closed ? 0 : byDay.get(d)?.sales ?? 0, exp.get(d) ?? 0]).concat(breakeven ?? 0)
  const top = Math.max(...vals, 1)
  const mag = 10 ** Math.floor(Math.log10(top / 4))
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s * 4 >= top) ?? mag * 10
  const yMax = Math.ceil(top / step) * step
  const x = (i: number) => L + (i / (dates.length - 1)) * (W - L - R)
  const y = (v: number) => T + (1 - v / yMax) * (H - T - B)
  const path = (get: (d: string) => number | undefined) => {
    let out = "", pen = false
    dates.forEach((d, i) => {
      const v = get(d)
      if (v === undefined) { pen = false; return }
      out += `${pen ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`
      pen = true
    })
    return out
  }
  const sold = (d: string) => { const r = byDay.get(d); return r ? (r.closed ? 0 : r.sales) : undefined }
  const [hover, setHover] = useState<number | null>(null)
  const svg = useRef<SVGSVGElement>(null)
  const onMove = (ev: React.PointerEvent) => {
    const r = svg.current?.getBoundingClientRect()
    if (!r) return
    const i = Math.round((((ev.clientX - r.left) / r.width) * W - L) / (W - L - R) * (dates.length - 1))
    setHover(Math.max(0, Math.min(dates.length - 1, i)))
  }
  const h = hover === null ? null : dates[hover]
  return (
    <figure style={{ margin: 0 }} data-testid="business-chart">
      <div className="h-launch-legend" aria-hidden>
        <span><i style={{ background: "var(--viz-1)" }} />What you sold</span>
        {expected.length > 0 && <span><i style={{ background: "var(--viz-2)" }} />What Hangul expected</span>}
        {breakeven ? <span><i style={{ background: "var(--muted)" }} />Break-even</span> : null}
      </div>
      <div style={{ position: "relative" }}>
        <svg ref={svg} viewBox={`0 0 ${W} ${H}`} width="100%" role="img" style={{ display: "block", touchAction: "pan-y" }}
          aria-label="Daily sales for the last six weeks, against what Hangul expected" onPointerMove={onMove} onPointerLeave={() => setHover(null)}>
          {Array.from({ length: Math.round(yMax / step) + 1 }, (_, i) => i * step).map((t) => (
            <g key={t}>
              <line x1={L} x2={W - R} y1={y(t)} y2={y(t)} stroke="var(--viz-grid)" strokeWidth={1} />
              <text x={L - 8} y={y(t) + 4} textAnchor="end" className="h-launch-tick">{rupees(t, true)}</text>
            </g>
          ))}
          {dates.map((d, i) => (i % 7 === 6 ? <text key={d} x={x(i)} y={H - 10} textAnchor="middle" className="h-launch-tick">{shortDate(d).replace(/^\w+,?\s/, "")}</text> : null))}
          {breakeven ? (
            <g>
              <line x1={L} x2={W - R} y1={y(breakeven)} y2={y(breakeven)} stroke="var(--muted)" strokeWidth={1} />
              <text x={W - R} y={y(breakeven) - 5} textAnchor="end" className="h-launch-tick">break-even {rupees(breakeven, true)}</text>
            </g>
          ) : null}
          {expected.length > 0 && <path d={path((d) => exp.get(d))} fill="none" stroke="var(--viz-2)" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />}
          <path d={path(sold)} fill="none" stroke="var(--viz-1)" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />
          {h && (
            <g pointerEvents="none">
              <line x1={x(hover!)} x2={x(hover!)} y1={T} y2={H - B} stroke="var(--fg)" strokeOpacity={0.3} strokeWidth={1} />
              {sold(h) !== undefined && <circle cx={x(hover!)} cy={y(sold(h)!)} r={4} fill="var(--viz-1)" stroke="var(--surface-solid)" strokeWidth={2} />}
              {exp.has(h) && <circle cx={x(hover!)} cy={y(exp.get(h)!)} r={4} fill="var(--viz-2)" stroke="var(--surface-solid)" strokeWidth={2} />}
            </g>
          )}
        </svg>
        {h && (
          <div className="h-launch-tip" role="status" style={{ left: `${Math.min(85, Math.max(15, (x(hover!) / W) * 100))}%` }}>
            <b>{shortDate(h)}</b>
            <span><i style={{ background: "var(--viz-1)" }} />{byDay.get(h)?.closed ? "Closed" : sold(h) !== undefined ? `Sold ${rupees(sold(h)!)}` : "Not logged"}</span>
            {exp.has(h) && <span><i style={{ background: "var(--viz-2)" }} />Expected {rupees(exp.get(h)!)}</span>}
          </div>
        )}
      </div>
    </figure>
  )
}
