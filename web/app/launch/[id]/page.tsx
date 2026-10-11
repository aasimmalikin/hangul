"use client"

import Link from "next/link"
import { use, useEffect, useState } from "react"
import { useSession } from "next-auth/react"
import { AppHeader } from "@/components/hangul/AppHeader"
import { SignInModal, type AuthMode } from "@/components/hangul/SignInModal"
import { LaunchDashboard } from "@/components/hangul/LaunchDashboard"
import { isRefusal, launchApi, type Plan } from "@/lib/launch"

const UNIT: Record<string, string> = { cloud_kitchen: "order", cafe: "bill", retail_shop: "bill", salon: "visit", d2c_brand: "order" }

/** One launch plan's dashboard. */
export default function LaunchPlanPage({ params }: { params: Promise<{ id: string }> }) {
  const { id: raw } = use(params)
  const id = Number(raw)
  const { status } = useSession()
  const [signIn, setSignIn] = useState<{ open: boolean; mode: AuthMode }>({ open: false, mode: "signin" })
  const [dismissed, setDismissed] = useState(false)
  const [plan, setPlan] = useState<Plan | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (status !== "authenticated" || !Number.isInteger(id)) return
    void launchApi.get(id).then((r) => {
      if (isRefusal(r)) setError(r.code === "bad_request" ? "This plan doesn't exist, or isn't yours." : r.detail)
      else setPlan(r)
    })
  }, [status, id])

  return (
    <main className="h-has-bottom-nav" style={{ minHeight: "100vh", display: "flex", flexDirection: "column" }}>
      <AppHeader onSignIn={() => setSignIn({ open: true, mode: "signin" })} onSignUp={() => setSignIn({ open: true, mode: "signup" })} />
      <SignInModal open={signIn.open || (status === "unauthenticated" && !dismissed)} mode={signIn.mode}
        onClose={() => { setDismissed(true); setSignIn((s) => ({ ...s, open: false })) }} callbackUrl={`/launch/${raw}`}
        reason="Sign in to see your plan." />
      <div className="h-studio-page">
        <Link href="/launch" className="h-muted" style={{ fontSize: 13, textDecoration: "none" }}>← All plans</Link>
        {plan && <LaunchDashboard initial={plan} unit={UNIT[plan.kind] ?? "sale"} />}
        {!plan && !error && status === "authenticated" && <span className="h-muted">Loading your plan…</span>}
        {error && <span role="alert" style={{ color: "var(--err)", fontSize: 14 }} data-testid="launch-error">{error}</span>}
      </div>
    </main>
  )
}
