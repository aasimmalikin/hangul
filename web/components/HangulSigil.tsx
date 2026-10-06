import { MARK_ANTLER, MARK_EAR, MARK_FACE, MARK_VIEWBOX } from "@/lib/brand"

/**
 * The Hangul mark (the Kashmir stag in profile, lib/brand.ts), drawn in the
 * theme's `--sigil` colour. Static; the living, tappable version on Today is
 * components/hangul/LivingStag.tsx.
 */
export function HangulSigil({ size = 32, className = "" }: { size?: number; className?: string }) {
  return (
    <svg width={size} height={size} viewBox={MARK_VIEWBOX} xmlns="http://www.w3.org/2000/svg"
      className={className} role="img" aria-label="Hangul" style={{ display: "block", overflow: "visible" }}>
      <g fill="var(--sigil)">
        <path d={MARK_EAR} />
        <path d={MARK_ANTLER} />
        <path d={MARK_FACE} fillRule="evenodd" />
      </g>
    </svg>
  )
}
