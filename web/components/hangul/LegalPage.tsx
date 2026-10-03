"use client"

import Link from "next/link"
import { useRouter } from "next/navigation"
import { AppHeader } from "@/components/hangul/AppHeader"
import { LEGAL, PLACEHOLDER } from "@/lib/legal"

/** Shared layout for /terms, /privacy and /refunds: readable width, headings, cross-links. */
export function LegalPage({ title, intro, children }: { title: string; intro: string; children: React.ReactNode }) {
  const router = useRouter()
  const missing = Object.values(LEGAL).some((v) => typeof v === "string" && PLACEHOLDER.test(v))
  return (
    <main style={{ minHeight: "100vh", display: "flex", flexDirection: "column" }}>
      <AppHeader onSignIn={() => router.push("/")} />
      <article className="h-prose" style={{ width: "100%", maxWidth: 720, margin: "0 auto", padding: "8px 20px 60px", boxSizing: "border-box", fontSize: 15, lineHeight: 1.65 }}>
        {missing && (
          <p className="h-surface" role="note" style={{ padding: "8px 12px", fontSize: 12, color: "var(--warn)" }} data-testid="legal-draft">
            Draft: fill in the bracketed details in <code>web/lib/legal.ts</code> and have this reviewed before launch.
          </p>
        )}
        <h1 className="h-display" style={{ fontSize: 30, margin: "12px 0 4px" }}>{title}</h1>
        <p className="h-muted" style={{ fontSize: 13, margin: "0 0 18px" }}>Last updated {LEGAL.lastUpdated}</p>
        <p>{intro}</p>
        {children}
        <hr style={{ border: 0, borderTop: "0.5px solid var(--surface-border)", margin: "32px 0 14px" }} />
        <p className="h-muted" style={{ fontSize: 13 }}>
          <Link href="/terms">Terms of Service</Link> · <Link href="/privacy">Privacy Policy</Link> · <Link href="/refunds">Refund Policy</Link>
          {" · "}Questions: <a href={`mailto:${LEGAL.contactEmail}`}>{LEGAL.contactEmail}</a>
        </p>
      </article>
    </main>
  )
}

export function H({ children }: { children: React.ReactNode }) {
  return <h2 className="h-display" style={{ fontSize: 20, margin: "28px 0 8px" }}>{children}</h2>
}
