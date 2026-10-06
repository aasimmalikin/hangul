"use client"

import { useCallback, useEffect, useId, useRef, useState } from "react"
import { MARK_ANTLER, MARK_EAR, MARK_EYE, MARK_HEAD, MARK_NOSTRIL, MARK_TIPS, MARK_VIEWBOX } from "@/lib/brand"

/**
 * The living Hangul stag on Today. It breathes, blinks, flicks an ear now and
 * then, turns its head toward the pointer, and sleeps after midnight. Tapping
 * it makes it look up (ear pricked, antler tips glinting) and offer what the
 * user usually asks at this time of day: `suggestion` from GET /api/today
 * (src/harness/habits.py), or a default for the hour while that loads.
 * A chip sends its prompt through `onAsk`, exactly like typing it.
 */
export type Suggestion = { kind: string; learned: boolean; line: string; chips: Array<{ label: string; prompt: string }> }

function fallback(hour: number): Suggestion {
  if (hour < 5) return { kind: "late", learned: false, line: "You're up late. Anything to remember for the morning?", chips: [{ label: "Set a reminder", prompt: "Remind me tomorrow at 9am to " }] }
  if (hour < 12) return { kind: "brief", learned: false, line: "Good morning. Want your brief for today?", chips: [{ label: "Brief me", prompt: "Give me my brief for today: the weather, my calendar, reminders and anything important in my email." }] }
  if (hour < 18) return { kind: "calendar", learned: false, line: "Want me to find free time this week?", chips: [{ label: "Find free time", prompt: "When am I free this week?" }] }
  return { kind: "tomorrow", learned: false, line: "Shall we plan tomorrow?", chips: [{ label: "Plan tomorrow", prompt: "Help me plan tomorrow." }] }
}

const REACT_MS = 2600
const BUBBLE_MS = 12_000

export function LivingStag({ suggestion, onAsk, size = 120 }: {
  suggestion?: Suggestion | null
  onAsk: (prompt: string) => void
  size?: number
}) {
  const maskId = useId().replace(/:/g, "")
  const ref = useRef<SVGSVGElement>(null)
  const [reacting, setReacting] = useState(false)
  const [flick, setFlick] = useState(false)
  const [asleep, setAsleep] = useState(false)
  const [open, setOpen] = useState(false)
  const [awakeUntil, setAwakeUntil] = useState(0)
  const timers = useRef<number[]>([])
  const later = (fn: () => void, ms: number) => { timers.current.push(window.setTimeout(fn, ms)) }

  // sleeps between midnight and 5 am (device time), unless just woken by a tap
  useEffect(() => {
    const check = () => setAsleep(new Date().getHours() < 5 && Date.now() > awakeUntil)
    check()
    const t = window.setInterval(check, 60_000)
    return () => window.clearInterval(t)
  }, [awakeUntil])

  // an ear flick every few seconds while awake
  useEffect(() => {
    let alive = true
    const loop = () => later(() => {
      if (!alive) return
      setFlick(true)
      later(() => setFlick(false), 340)
      loop()
    }, 5000 + Math.random() * 9000)
    loop()
    const pending = timers.current
    return () => { alive = false; pending.forEach(clearTimeout) }
  }, [])

  // the head follows the pointer, a little, when it is near
  useEffect(() => {
    let raf = 0
    const onMove = (e: PointerEvent) => {
      if (raf) return
      raf = requestAnimationFrame(() => {
        raf = 0
        const el = ref.current
        if (!el) return
        const r = el.getBoundingClientRect()
        const cy = r.top + r.height * 0.45
        const dist = Math.hypot(e.clientX - (r.left + r.width / 2), e.clientY - cy)
        const fade = Math.max(0, 1 - dist / 700)
        const deg = Math.max(-6, Math.min(6, ((e.clientY - cy) / (r.height * 0.8)) * 7)) * fade
        el.style.setProperty("--look", `${deg.toFixed(2)}deg`)
      })
    }
    window.addEventListener("pointermove", onMove)
    return () => { window.removeEventListener("pointermove", onMove); cancelAnimationFrame(raf) }
  }, [])

  // TodayTalk asks for a cheer when something gets done: look up and glint, no bubble
  useEffect(() => {
    const cheer = () => {
      setAsleep(false)
      setReacting(false)
      requestAnimationFrame(() => setReacting(true))
      window.setTimeout(() => setReacting(false), REACT_MS)
    }
    window.addEventListener("hangul:stag-cheer", cheer)
    return () => window.removeEventListener("hangul:stag-cheer", cheer)
  }, [])

  const react = useCallback(() => {
    setAwakeUntil(Date.now() + 15_000)
    setAsleep(false)
    setReacting(false)
    requestAnimationFrame(() => setReacting(true))       // restart the glint animation on every tap
    later(() => setReacting(false), REACT_MS)
    setOpen(true)
    later(() => setOpen(false), BUBBLE_MS)
  }, [])

  const s = suggestion ?? fallback(new Date().getHours())
  const cls = ["h-stag", reacting && "is-react", flick && !asleep && "is-flick", asleep && !reacting && "is-asleep"].filter(Boolean).join(" ")

  return (
    <div className="h-stag-wrap" data-testid="living-stag">
      <svg ref={ref} className={cls} viewBox={MARK_VIEWBOX} width={size} height={size} role="button" tabIndex={0}
        aria-label="Hangul. Tap for a suggestion" aria-expanded={open} data-testid="living-stag-tap"
        onClick={react} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); react() } }}>
        <defs>
          <mask id={maskId} maskUnits="userSpaceOnUse" x="0" y="-40" width="260" height="260">
            <rect x="0" y="-40" width="260" height="260" fill="white" />
            <ellipse className="h-stag-eye" cx={MARK_EYE.cx} cy={MARK_EYE.cy} rx={MARK_EYE.r} ry={MARK_EYE.r} fill="black" />
          </mask>
        </defs>
        <g className="h-stag-body">
          <g className="h-stag-head">
            <path className="h-stag-ear" d={MARK_EAR} />
            <path d={MARK_ANTLER} />
            <path d={`${MARK_HEAD} ${MARK_NOSTRIL}`} fillRule="evenodd" mask={`url(#${maskId})`} />
            <g className="h-stag-glints">
              {MARK_TIPS.map(([x, y], i) => <circle key={i} cx={x} cy={y} r={3} style={{ ["--i" as string]: i }} />)}
            </g>
          </g>
        </g>
        <g className="h-stag-arcs">
          <path style={{ ["--i" as string]: 0 }} d="M174,82 Q180,90 174,98" />
          <path style={{ ["--i" as string]: 1 }} d="M181,76 Q190,90 181,104" />
        </g>
        <g className="h-stag-zz">
          {[[150, 66, 2], [160, 56, 2.6], [172, 44, 3.2]].map(([x, y, r], i) => <circle key={i} cx={x} cy={y} r={r} style={{ ["--i" as string]: i }} />)}
        </g>
      </svg>
      {open && (
        <div className="h-popover h-stag-bubble" role="status" data-testid="living-stag-bubble">
          <span className="h-stag-who">{s.learned ? "Hangul noticed" : "Hangul"}</span>
          <span style={{ fontSize: 14, lineHeight: 1.45 }}>{s.line}</span>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {s.chips.map((c, i) => (
              <button key={c.label} type="button" className={i === 0 ? "h-btn-solid" : "h-chip"} data-testid="living-stag-chip"
                style={i === 0 ? { padding: "6px 12px", borderRadius: 999 } : undefined}
                onClick={() => { setOpen(false); onAsk(c.prompt) }}>{c.label}</button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
