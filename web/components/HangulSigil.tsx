export function HangulSigil({ size = 32, className = "" }: { size?: number; className?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 120 130" fill="none"
      xmlns="http://www.w3.org/2000/svg" className={className}
      role="img" aria-label="Hangul">
      <g stroke="var(--sigil)" strokeWidth="6" strokeLinecap="round" strokeLinejoin="round">
        <path d="M60 120 C60 88 48 72 34 56 C22 42 18 24 24 4" />
        <path d="M60 120 C60 88 72 72 86 56 C98 42 102 24 96 4" />
        <path d="M38 60 C24 54 12 42 6 24" />
        <path d="M82 60 C96 54 108 42 114 24" />
      </g>
    </svg>
  )
}
