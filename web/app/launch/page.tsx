"use client"

import Link from "next/link"
import { useCallback, useEffect, useState } from "react"
import { useSession } from "next-auth/react"
import { AppHeader } from "@/components/hangul/AppHeader"
import { SignInModal, type AuthMode } from "@/components/hangul/SignInModal"
import { LaunchForm } from "@/components/hangul/LaunchForm"
import { isRefusal, KIND_ICON, launchApi, rupees, type PlanSummary } from "@/lib/launch"

/**
 * Launch plans: what it takes to start a business. The list of the user's
 * plans, and the questions that make a new one (shown straight away when
 * there are none).
 */
function PlanCard({ p, onRemove }: { p: PlanSummary; onRemove: (id: number) => void }) {
  const [confirm, setConfirm] = useState(false)
  return (
    <article className="h-launch-card" data-testid="launch-card">
      <Link href={`/launch/${p.id}`} className="h-launch-card-link">
        <i className={`ti ti-${KIND_ICON[p.kind] ?? "building"}`} />
        <span style={{ minWidth: 0 }}>
          <b>{p.title}</b>
          <span className="h-muted" style={{ fontSize: 13 }}>
            {rupees(p.startup_total, true)} to start · break-even {p.breakeven_per_day ?? "—"}/day
            {p.payback_months ? ` · pays back in ${p.payback_months} months` : ""}
          </span>
        </span>
        <span className="h-badge" data-tone={p.status === "sourcing" ? "brand" : p.sourced ? "ok" : undefined} style={{ marginLeft: "auto" }}>
          {p.status === "sourcing" ? "Searching…" : p.sourced ? "Live prices" : "Estimates"}
        </span>
      </Link>
      {confirm
        ? <span style={{ display: "flex", gap: 4 }}>
            <button className="h-btn-ghost" style={{ fontSize: 12, color: "var(--err)" }} onClick={() => onRemove(p.id)} data-testid="launch-remove-confirm">Remove</button>
            <button className="h-btn-ghost" style={{ fontSize: 12 }} onClick={() => setConfirm(false)}>Keep</button>
          </span>
        : <button className="h-btn-ghost" onClick={() => setConfirm(true)} aria-label={`Remove ${p.title}`} data-testid="launch-remove">
            <i className="ti ti-trash" />
          </button>}
    </article>
  )
}

export default function LaunchPage() {
  const { status } = useSession()
  const [signIn, setSignIn] = useState<{ open: boolean; mode: AuthMode }>({ open: false, mode: "signin" })
  const [dismissed, setDismissed] = useState(false)
  const [plans, setPlans] = useState<PlanSummary[] | null>(null)
  const [adding, setAdding] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    const r = await launchApi.list()
    if (isRefusal(r)) setError("Couldn't load your plans right now.")
    else setPlans(r)
  }, [])

  useEffect(() => {
    if (status !== "authenticated") return
    // Fetch-on-sign-in; state is set after the await.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load()
  }, [status, load])

  const remove = async (id: number) => {
    const r = await launchApi.remove(id)
    if (r?.ok) void load()
    else setError("Couldn't remove that plan. Try again in a moment.")
  }

  const showForm = adding || (plans !== null && plans.length === 0)
  return (
    <main className="h-has-bottom-nav" style={{ minHeight: "100vh", display: "flex", flexDirection: "column" }}>
      <AppHeader onSignIn={() => setSignIn({ open: true, mode: "signin" })} onSignUp={() => setSignIn({ open: true, mode: "signup" })} />
      <SignInModal open={signIn.open || (status === "unauthenticated" && !dismissed)} mode={signIn.mode}
        onClose={() => { setDismissed(true); setSignIn((s) => ({ ...s, open: false })) }} callbackUrl="/launch"
        reason="Sign in to plan your business." />
      <div className="h-studio-page">
        <div className="h-studio-hero">
          <div>
            <h1>Start a business</h1>
            <p>Answer a few questions. Hangul lists what you&apos;ll need, finds prices and sellers, and works out what it
              costs to start, when you break even and when it pays back.</p>
          </div>
          {!showForm && (
            <button className="h-btn-solid" onClick={() => setAdding(true)} data-testid="launch-new">
              <i className="ti ti-plus" /> Plan a new business
            </button>
          )}
        </div>
        {showForm && <LaunchForm onCancel={plans && plans.length ? () => setAdding(false) : undefined} />}
        {plans && plans.length > 0 && (
          <>
            <div className="h-studio-section-title">Your plans</div>
            <div className="h-launch-list">
              {plans.map((p) => <PlanCard key={p.id} p={p} onRemove={(id) => void remove(id)} />)}
            </div>
          </>
        )}
        {error && <span role="alert" style={{ color: "var(--err)", fontSize: 13 }}>{error}</span>}
      </div>
    </main>
  )
}
