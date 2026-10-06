"use client"

import { useEffect, useId, useRef } from "react"
import { MARK_ANTLER, MARK_EAR, MARK_EAR_PIVOT, MARK_FACE, MARK_PIVOT, MARK_TIPS, MARK_VIEWBOX } from "@/lib/brand"
import type { VoiceMeter } from "@/lib/voice"

/**
 * The stag in voice mode: the app icon (white stag on a chinar-red disc),
 * moved by the voice. While Hangul speaks, every word sends a ripple out
 * from the disc, the head lifts on syllables, the ear flicks on stressed
 * words and the antler tips glint with the pitch (brow tine low, crown high).
 * Listening pricks the ear and ripples with the user's voice; thinking
 * breathes and runs a glint along the tines.
 *
 * Driven by `meter()` once per frame and drawn by mutating the SVG directly,
 * so it never re-renders React 60 times a second. When the browser gives no
 * meter while speaking, a plausible voice is made up so it still moves.
 */

export type StagPhase = "idle" | "asking" | "listening" | "transcribing" | "thinking" | "speaking"

const NS = "http://www.w3.org/2000/svg"
const DISC_R = 58
// tips in MARK_TIPS order -> which voice band (0 = low) each follows
const TIP_BAND = [2, 0, 1, 3, 4]

export function SpeakingStag({ phase, meter, size = 220 }: {
  phase: StagPhase
  /** Called every frame: the voice that is playing (speaking) or being heard (listening). */
  meter: () => VoiceMeter | null
  size?: number
}) {
  const glowId = `stag-glow-${useId().replace(/:/g, "")}`
  const disc = useRef<SVGCircleElement>(null)
  const rings = useRef<SVGGElement>(null)
  const head = useRef<SVGGElement>(null)
  const ear = useRef<SVGPathElement>(null)
  const tips = useRef<(SVGCircleElement | null)[]>([])
  const phaseRef = useRef(phase)
  const meterRef = useRef(meter)
  useEffect(() => { phaseRef.current = phase; meterRef.current = meter }, [phase, meter])

  useEffect(() => {
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches
    let env = 0, prevEnv = 0, earKick = 0, lastRing = 0, raf = 0
    const bands = [0, 0, 0, 0, 0]
    const live: { c: SVGCircleElement; t0: number; strength: number; slow: boolean }[] = []
    // a made-up voice for when there is no real meter: syllables, words, pauses
    let fakeTarget = 0, fakeNext = 0, syll = 0
    const fakeBands = [0, 0, 0, 0, 0]
    const fake = (now: number): VoiceMeter => {
      if (now >= fakeNext) {
        if (fakeTarget > 0) {
          syll++
          fakeTarget = 0
          fakeNext = now + (syll % 11 === 0 ? 600 : syll % 3 === 0 ? 170 : 55) * (0.7 + Math.random() * 0.6)
        } else {
          fakeTarget = 0.45 + Math.random() * 0.5
          fakeNext = now + 110 + Math.random() * 170
          for (let i = 0; i < 5; i++) fakeBands[i] = fakeTarget * (0.35 + Math.random() * 0.7)
        }
      }
      return { level: fakeTarget, bands: fakeTarget ? fakeBands : [0, 0, 0, 0, 0] }
    }

    const frame = (now: number) => {
      const ph = phaseRef.current
      const speaking = ph === "speaking", listening = ph === "listening"
      const thinking = ph === "thinking" || ph === "transcribing"
      const m = speaking || listening ? (meterRef.current() ?? (speaking ? fake(now) : null)) : null
      const level = m?.level ?? 0
      prevEnv = env
      env += (level - env) * (level > env ? 0.45 : 0.18)
      for (let i = 0; i < 5; i++) bands[i] += ((m?.bands[i] ?? 0) - bands[i]) * 0.3

      // ripples: one per word (a rise in loudness)
      if ((speaking || listening) && !reduce && env > 0.3 && prevEnv <= 0.3 && now - lastRing > 160 && rings.current) {
        const c = document.createElementNS(NS, "circle")
        c.setAttribute("cx", "100"); c.setAttribute("cy", "100"); c.setAttribute("fill", "none")
        rings.current.appendChild(c)
        live.push({ c, t0: now, strength: env, slow: listening })
        lastRing = now
      }
      for (let i = live.length - 1; i >= 0; i--) {
        const r = live[i], k = (now - r.t0) / (r.slow ? 1600 : 1300)
        if (k >= 1) { r.c.remove(); live.splice(i, 1); continue }
        r.c.setAttribute("r", (DISC_R + k * 42).toFixed(1))
        r.c.setAttribute("stroke-width", (3 * (1 - k) + 0.5).toFixed(2))
        r.c.style.opacity = ((1 - k) * (r.slow ? 0.5 : 0.4 + r.strength * 0.6)).toFixed(2)
      }

      // the disc swells with the voice and breathes while thinking
      const swell = speaking ? env * 5 : listening ? 2 + env * 3 : thinking ? 1.5 + Math.sin(now / 420) * 1.5 : 0
      disc.current?.setAttribute("r", (DISC_R + (reduce ? 0 : swell)).toFixed(2))
      if (disc.current) disc.current.style.opacity = ph === "asking" ? "0.55" : reduce && speaking ? (0.75 + env * 0.25).toFixed(2) : "1"

      // head lifts on syllables, tilts to listen; the ear flicks on stressed words, pricks to listen
      if (speaking && env > 0.75 && prevEnv <= 0.75) earKick = 1
      earKick *= 0.9
      const lift = reduce ? 0 : speaking ? -env * 4 : listening ? 3 : 0
      const earDeg = reduce ? 0 : listening ? 16 : earKick * 14
      head.current?.setAttribute("transform", `rotate(${lift.toFixed(2)} ${MARK_PIVOT.x} ${MARK_PIVOT.y})`)
      ear.current?.setAttribute("transform", `rotate(${earDeg.toFixed(2)} ${MARK_EAR_PIVOT.x} ${MARK_EAR_PIVOT.y})`)

      // antler tips glint with the pitch; while thinking a glint runs along the tines
      tips.current.forEach((t, i) => {
        if (!t) return
        let v = 0
        if (speaking) v = bands[TIP_BAND[i]]
        else if (listening) v = 0.15 + bands[TIP_BAND[i]] * 0.25
        else if (thinking && !reduce) v = Math.max(0, Math.sin(now / 260 - TIP_BAND[i] * 0.9)) * 0.7
        t.setAttribute("r", (reduce ? 4 : 2 + v * 6).toFixed(2))
        t.style.opacity = Math.min(1, v * 1.4).toFixed(2)
      })
      raf = requestAnimationFrame(frame)
    }
    raf = requestAnimationFrame(frame)
    return () => { cancelAnimationFrame(raf); live.forEach((r) => r.c.remove()) }
  }, [])

  return (
    <svg width={size} height={size} viewBox="-10 -10 220 220" aria-hidden data-testid="speaking-stag" data-phase={phase}
      style={{ display: "block", overflow: "visible" }}>
      <defs>
        <filter id={glowId} x="-100%" y="-100%" width="300%" height="300%"><feGaussianBlur stdDeviation="2.2" /></filter>
      </defs>
      <g ref={rings} stroke="var(--solid-bg)" />
      <circle ref={disc} cx={100} cy={100} r={DISC_R} fill="var(--solid-bg)" />
      <svg x={48} y={44} width={104} height={110} viewBox={MARK_VIEWBOX} overflow="visible">
        <g ref={head} fill="var(--solid-fg)">
          <path ref={ear} d={MARK_EAR} />
          <path d={MARK_ANTLER} />
          <path d={MARK_FACE} fillRule="evenodd" />
          <g filter={`url(#${glowId})`}>
            {MARK_TIPS.map(([x, y], i) => (
              <circle key={i} ref={(el) => { tips.current[i] = el }} cx={x} cy={y} r={2} style={{ opacity: 0 }} />
            ))}
          </g>
        </g>
      </svg>
    </svg>
  )
}
