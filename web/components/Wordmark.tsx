import Link from "next/link"
import { HangulSigil } from "@/components/HangulSigil"

/**
 * The product signature: sigil beside the name, set in the display serif with
 * the tight tracking a wordmark wants. Sits in the top-left of every page.
 *
 * Pass href={null} on the page it would link to, so it renders as plain mark
 * rather than a link to where the user already is.
 */
export function Wordmark({
  size = 22,
  href = "/",
  className = "",
}: {
  size?: number
  href?: string | null
  className?: string
}) {
  const inner = (
    <>
      <HangulSigil size={size} />
      <span
        className="font-[family-name:var(--font-fraunces)] font-medium leading-none tracking-[-0.02em] text-foreground"
        style={{ fontSize: size * 0.95 }}
      >
        Hangul
      </span>
    </>
  )

  const base = `inline-flex items-center gap-2 ${className}`

  if (!href) {
    return (
      <span className={base} aria-label="Hangul">
        {inner}
      </span>
    )
  }

  return (
    <Link
      href={href}
      aria-label="Hangul home"
      className={`${base} rounded-md opacity-90 transition-opacity hover:opacity-100 focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-ring`}
    >
      {inner}
    </Link>
  )
}
