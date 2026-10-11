"use client"

import Link from "next/link"
import { useEffect, useState } from "react"
import { signOut, useSession } from "next-auth/react"
import { AppHeader } from "@/components/hangul/AppHeader"
import { SignInModal, type AuthMode } from "@/components/hangul/SignInModal"
import { LEGAL } from "@/lib/legal"

/**
 * You: everything about the account in one place -- profile & preferences,
 * connected apps, plan & billing -- instead of three separate menu entries.
 */
type BillingSummary = { enabled: boolean; plan: string; plan_label?: string }
type Integrations = { google: { connected: boolean; products: string[] }; apps?: Record<string, boolean> }
type Memory = { id: number; kind: string; content: string; created_at: string }

/**
 * What Hangul remembers about the user (the agent's `remember` tool): GET
 * /api/memory, and Forget = DELETE /api/memory/<id>. Hidden while empty.
 */
function Memories() {
  const [items, setItems] = useState<Memory[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    void fetch("/api/memory", { cache: "no-store" }).then((r) => (r.ok ? r.json() : [])).then(setItems).catch(() => setItems([]))
  }, [])
  const forget = async (id: number) => {
    setError(null)
    const res = await fetch(`/api/memory/${id}`, { method: "DELETE" }).catch(() => null)
    if (res?.ok) setItems((xs) => (xs ?? []).filter((m) => m.id !== id))
    else setError("Couldn't forget that right now. Try again in a moment.")
  }
  if (!items?.length) return null
  return (
    <section className="h-surface" data-testid="you-memory" style={{ padding: "14px 16px", borderRadius: 14, display: "flex", flexDirection: "column", gap: 8 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <i className="ti ti-brain" style={{ fontSize: 22 }} />
        <span style={{ flex: 1 }}>
          <span style={{ display: "block", fontSize: 15, fontWeight: 500 }}>What Hangul remembers</span>
          <span className="h-muted" style={{ fontSize: 12 }}>Things you told it to keep in mind. Forget any of them at any time.</span>
        </span>
      </div>
      <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "flex", flexDirection: "column" }}>
        {items.map((m) => (
          <li key={m.id} data-testid="you-memory-item" style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 0", borderTop: "0.5px solid var(--surface-border)", fontSize: 14 }}>
            <span style={{ flex: 1, minWidth: 0 }}>{m.content}</span>
            <button className="h-btn-ghost" onClick={() => void forget(m.id)} data-testid="you-memory-forget" style={{ fontSize: 12 }}>Forget</button>
          </li>
        ))}
      </ul>
      {error && <span style={{ color: "var(--err)", fontSize: 12 }}>{error}</span>}
    </section>
  )
}

function Row({ href, icon, title, detail, testId }: { href: string; icon: string; title: string; detail: string; testId: string }) {
  return (
    <Link href={href} className="h-surface" data-testid={testId}
      style={{ display: "flex", alignItems: "center", gap: 14, padding: "14px 16px", textDecoration: "none", color: "var(--fg)", borderRadius: 14 }}>
      <i className={`ti ti-${icon}`} style={{ fontSize: 22 }} />
      <span style={{ flex: 1, minWidth: 0 }}>
        <span style={{ display: "block", fontSize: 15, fontWeight: 500 }}>{title}</span>
        <span className="h-muted" style={{ fontSize: 12 }}>{detail}</span>
      </span>
      <i className="ti ti-chevron-right" style={{ fontSize: 16, color: "var(--muted)" }} />
    </Link>
  )
}

export default function YouPage() {
  const { data: session, status } = useSession()
  const [signIn, setSignIn] = useState<{ open: boolean; mode: AuthMode }>({ open: false, mode: "signin" })
  const [dismissed, setDismissed] = useState(false)
  const [billing, setBilling] = useState<BillingSummary | null>(null)
  const [integ, setInteg] = useState<Integrations | null>(null)

  useEffect(() => {
    if (status !== "authenticated") return
    // Fetch-on-sign-in; state is set after the awaits.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void fetch("/api/billing", { cache: "no-store" }).then((r) => (r.ok ? r.json() : null)).then(setBilling).catch(() => {})
    void fetch("/api/integrations", { cache: "no-store" }).then((r) => (r.ok ? r.json() : null)).then(setInteg).catch(() => {})
  }, [status])

  const apps = [
    ...(integ?.google.connected ? ["Google"] : []),
    ...Object.entries(integ?.apps ?? {}).filter(([, on]) => on).map(([k]) => k[0].toUpperCase() + k.slice(1)),
  ]
  const user = session?.user

  return (
    <main className="h-has-bottom-nav" style={{ minHeight: "100vh", display: "flex", flexDirection: "column" }}>
      <AppHeader onSignIn={() => setSignIn({ open: true, mode: "signin" })} onSignUp={() => setSignIn({ open: true, mode: "signup" })} />
      <SignInModal open={signIn.open || (status === "unauthenticated" && !dismissed)} mode={signIn.mode}
        onClose={() => { setDismissed(true); setSignIn((s) => ({ ...s, open: false })) }} callbackUrl="/you" reason="Sign in to manage your account." />
      <div style={{ width: "100%", maxWidth: 640, margin: "0 auto", padding: "8px 16px 40px", display: "flex", flexDirection: "column", gap: 12, boxSizing: "border-box" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 14, margin: "8px 0 6px" }} data-testid="you-header">
          <span style={{ width: 48, height: 48, borderRadius: "50%", display: "grid", placeItems: "center", fontSize: 20, background: "var(--surface-hover)" }}>
            {(user?.name ?? user?.email ?? "?")[0]?.toUpperCase()}
          </span>
          <div>
            <h1 className="h-display" style={{ fontSize: 22, margin: 0 }}>{user?.name ?? "You"}</h1>
            <div className="h-muted" style={{ fontSize: 13 }}>{user?.email}</div>
          </div>
        </div>
        <Row href="/kept" icon="bookmark" title="Kept" testId="you-kept"
          detail="What Hangul did for you, and anything waiting for your OK" />
        <Row href="/settings" icon="adjustments" title="Profile & preferences" testId="you-preferences"
          detail="Your name, city, tone, timezone, custom instructions and scheduled tasks" />
        <Row href="/vault" icon="plug-connected" title="Connected apps" testId="you-apps"
          detail={apps.length ? `Connected: ${apps.join(", ")}` : "Connect Google: Gmail, Calendar, Drive, Docs, Sheets"} />
        <Row href="/brands" icon="palette" title="Brands" testId="you-brands"
          detail="Your business's colours, font and logo, used for posts, posters and files" />
        <Row href="/business" icon="trending-up" title="How's business" testId="you-business"
          detail="Your sales, tomorrow's forecast, and what to do about a slow day" />
        <Row href="/customers" icon="users" title="Customers" testId="you-customers"
          detail="Your regulars, their birthdays, and who hasn't been in for a while" />
        <Row href="/missions" icon="checklist" title="Slow days, handled" testId="you-missions"
          detail="Hangul makes the offer, asks you once, and shows what it earned" />
        <Row href="/launch" icon="rocket" title="Start a business" testId="you-launch"
          detail="What you'd need, what it costs, and when it breaks even" />
        <Row href="/billing" icon="credit-card" title="Plan & billing" testId="you-plan"
          detail={billing?.enabled ? `You're on ${billing.plan_label ?? billing.plan}` : "Your plan and usage"} />
        {status === "authenticated" && <Memories />}
        <button className="h-btn-ghost" onClick={() => signOut({ redirectTo: "/" })} style={{ alignSelf: "flex-start", marginTop: 8, gap: 6 }}>
          <i className="ti ti-logout" style={{ fontSize: 15 }} /> Sign out
        </button>
        <p className="h-muted" style={{ fontSize: 12, margin: "8px 0 0" }} data-testid="you-legal">
          <Link href="/terms" style={{ color: "inherit" }}>Terms</Link> · <Link href="/privacy" style={{ color: "inherit" }}>Privacy</Link> ·{" "}
          <Link href="/refunds" style={{ color: "inherit" }}>Refunds</Link> · To delete your account, email {LEGAL.contactEmail}
        </p>
      </div>
    </main>
  )
}
