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
        <Row href="/settings" icon="adjustments" title="Profile & preferences" testId="you-preferences"
          detail="Your name, city, tone, timezone, custom instructions and scheduled tasks" />
        <Row href="/vault" icon="plug-connected" title="Connected apps" testId="you-apps"
          detail={apps.length ? `Connected: ${apps.join(", ")}` : "Connect Google, GitHub, Notion or Slack"} />
        <Row href="/billing" icon="credit-card" title="Plan & billing" testId="you-plan"
          detail={billing?.enabled ? `You're on ${billing.plan_label ?? billing.plan}` : "Your plan and usage"} />
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
