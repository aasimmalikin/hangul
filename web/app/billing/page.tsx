"use client"

import { Suspense, useCallback, useEffect, useState } from "react"
import { useSearchParams } from "next/navigation"
import { useSession } from "next-auth/react"
import { CancelFlow } from "@/components/hangul/CancelFlow"
import { AppHeader } from "@/components/hangul/AppHeader"
import { SignInModal, type AuthMode } from "@/components/hangul/SignInModal"

/**
 * /billing — the user's plan, what is left of this period's allowance, bought
 * credits, and the way to upgrade or top up. Payment happens on Dodo
 * Payments' hosted checkout; the plan changes when its webhook arrives, so
 * the page re-reads /api/billing on return.
 */

type PlanInfo = { id: string; label: string; price_usd_month: number; model_tiers: string[]; max_effort: string; research_allowed: boolean; monthly_allowance_usd: number }
type Billing = {
  enabled: boolean
  plan: string
  plan_label?: string
  status?: string | null
  renews_at?: string | null
  ends_at?: string | null
  allowance_usd?: number
  allowance_left_usd?: number
  credits_usd?: number
  free_pool_exhausted?: boolean
  has_portal?: boolean
  messages_left?: number
  messages_total?: number
  trialing?: boolean
  trial_ends_at?: string | null
  trial_days?: number
  plans: PlanInfo[]
}

const usd = (n: number) => `$${n.toFixed(2)}`
const day = (iso?: string | null) => (iso ? new Date(iso).toLocaleDateString() : null)
const TIER_TEXT: Record<string, string> = { basic: "Fast everyday models", advanced: "Advanced models (GPT-5.4, Terra…)", frontier: "Frontier models (GPT-5.5, Sol, Astra)" }

function Section({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <section className="h-surface" style={{ padding: "18px 20px", display: "flex", flexDirection: "column", gap: 12 }}>
      <div>
        <h2 className="h-display" style={{ fontSize: 18, margin: 0 }}>{title}</h2>
        {hint && <p className="h-muted" style={{ fontSize: 12, margin: "4px 0 0" }}>{hint}</p>}
      </div>
      {children}
    </section>
  )
}

function BillingInner() {
  const params = useSearchParams()
  const highlight = params.get("upgrade")
  const { status: authStatus } = useSession()
  const [signIn, setSignIn] = useState<{ open: boolean; mode: AuthMode }>({ open: false, mode: "signin" })
  const [gateDismissed, setGateDismissed] = useState(false)
  const signInOpen = signIn.open || (authStatus === "unauthenticated" && !gateDismissed)

  const [billing, setBilling] = useState<Billing | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [cancelling, setCancelling] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const res = await fetch("/api/billing", { cache: "no-store" })
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? `Request failed (${res.status})`)
      setBilling(await res.json())
    } catch (e) { setError((e as Error).message) }
  }, [])

  useEffect(() => {
    if (authStatus !== "authenticated") return
    // Fetch-on-sign-in; state is set after the await (same pattern as /settings).
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load()
  }, [authStatus, load])

  // Both return a provider-hosted URL to send the browser to.
  const redirectTo = async (key: string, path: string, body?: unknown) => {
    setBusy(key); setError(null)
    try {
      const res = await fetch(path, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined,
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok || !data.url) throw new Error(data.detail ?? `Request failed (${res.status})`)
      window.location.href = data.url
    } catch (e) { setError((e as Error).message); setBusy(null) }
  }
  const checkout = (product: "plus" | "pro" | "topup") => redirectTo(product, "/api/billing/checkout", { product })
  const openPortal = () => redirectTo("portal", "/api/billing/portal")
  const resume = async () => {
    setBusy("resume"); setError(null)
    try {
      const res = await fetch("/api/billing/resume", { method: "POST" })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : `Request failed (${res.status})`)
      setNotice("You're staying — your plan will renew as usual.")
      await load()
    } catch (e) { setError((e as Error).message) } finally { setBusy(null) }
  }

  const b = billing
  const allowance = b?.allowance_usd ?? 0
  const left = b?.allowance_left_usd ?? 0
  const usedPct = allowance > 0 ? Math.min(100, Math.round(((allowance - left) / allowance) * 100)) : 0
  // dollars per message, from the backend's estimate; used to show each plan as "about N messages"
  const perMessage = allowance > 0 && b?.messages_total ? allowance / b.messages_total : 0.01
  const ending = b?.status === "cancelling" || b?.status === "trial_cancelling"
  const rank = (id: string) => b?.plans.findIndex((p) => p.id === id) ?? 0

  return (
    <main className="h-has-bottom-nav" style={{ minHeight: "100vh", display: "flex", flexDirection: "column" }}>
      <AppHeader onSignIn={() => setSignIn({ open: true, mode: "signin" })} onSignUp={() => setSignIn({ open: true, mode: "signup" })} />
      <SignInModal open={signInOpen} mode={signIn.mode} onClose={() => { setGateDismissed(true); setSignIn((s) => ({ ...s, open: false })) }} callbackUrl="/billing" reason="Sign in to manage your plan." />

      <div style={{ width: "100%", maxWidth: 760, margin: "0 auto", padding: "8px 16px 40px", display: "flex", flexDirection: "column", gap: 16, boxSizing: "border-box" }}>
        <div>
          <h1 className="h-display" style={{ fontSize: 26, margin: "8px 0 4px" }}>Plan & billing</h1>
          <p className="h-muted" style={{ fontSize: 13, margin: 0 }}>Everyday models are free. Stronger models, higher effort and deep research come with a paid plan.</p>
        </div>
        {error && <div className="h-surface" style={{ padding: 12, fontSize: 13, color: "var(--err)" }} role="alert">{error}</div>}

        {b && !b.enabled && (
          <div className="h-surface" style={{ padding: 12, fontSize: 13 }} data-testid="billing-disabled">
            Billing isn&apos;t switched on for this deployment — every model is available.
          </div>
        )}

        {b?.free_pool_exhausted && (
          <div className="h-surface" role="status" data-testid="free-pool-full"
            style={{ padding: 12, fontSize: 13, background: "var(--warn-bg)", border: "0.5px solid var(--warn)" }}>
            Free capacity is full for this month. Upgrade or buy credits to keep asking — it frees up again on the 1st.
          </div>
        )}

        {b?.enabled && (
          <Section title={`Current plan: ${b.plan_label ?? b.plan}`}
            hint={b.trialing && b.status !== "trial_cancelling" ? `Free trial — ends ${day(b.trial_ends_at) ?? "soon"}, then $${b.plans.find((p) => p.id === b.plan)?.price_usd_month ?? 20}/month unless you cancel.`
              : ending && b.ends_at ? `Cancelled — stays active until ${day(b.ends_at)}.`
              : b.renews_at ? `Renews ${day(b.renews_at)}.` : b.plan === "free" ? "Allowance resets on the 1st of each month." : undefined}>
            <div data-testid="allowance">
              <div className="flex" style={{ justifyContent: "space-between", fontSize: 13 }}>
                <span>{b.trialing ? "Included in your trial" : "Included usage this period"}</span>
                <span data-testid="messages-left">
                  {b.messages_total ? <>About <strong>{b.messages_left ?? 0}</strong> of {b.messages_total} messages left</> : `${usd(left)} of ${usd(allowance)} left`}
                </span>
              </div>
              <div style={{ height: 6, borderRadius: 999, background: "var(--surface-hover)", marginTop: 6, overflow: "hidden" }}>
                <div style={{ width: `${usedPct}%`, height: "100%", background: usedPct >= 90 ? "var(--warn)" : "var(--fg)" }} />
              </div>
            </div>
            <div className="flex" style={{ justifyContent: "space-between", alignItems: "center", fontSize: 13, gap: 12, flexWrap: "wrap" }}>
              <span>Credits: <strong data-testid="credits">{usd(b.credits_usd ?? 0)}</strong> <span className="h-muted">(used after the allowance; never expire)</span></span>
              <div className="flex gap-2">
                <button className="h-btn-ghost" onClick={() => checkout("topup")} disabled={busy !== null} data-testid="buy-credits">
                  {busy === "topup" ? "Opening…" : "Buy credits"}
                </button>
                {b.has_portal && (
                  <button className="h-btn-ghost" onClick={openPortal} disabled={busy !== null} data-testid="manage-subscription">
                    {busy === "portal" ? "Opening…" : "Manage subscription"}
                  </button>
                )}
              </div>
            </div>
            {notice && <div className="h-surface" role="status" style={{ padding: "8px 12px", fontSize: 13 }} data-testid="billing-notice">{notice}</div>}
            {b.plan !== "free" && b.has_portal && (ending ? (
              <div className="flex" style={{ alignItems: "center", gap: 10, fontSize: 13, flexWrap: "wrap" }} data-testid="plan-ending">
                <span style={{ flex: 1 }}>Your {b.plan_label ?? b.plan} plan ends on {day(b.ends_at) ?? "the end of this period"}. Changed your mind?</span>
                <button className="h-btn-solid" disabled={busy !== null} onClick={() => void resume()} data-testid="resume-plan">Keep my plan</button>
              </div>
            ) : (
              <button className="h-btn-ghost" onClick={() => setCancelling(true)} data-testid="cancel-plan"
                style={{ alignSelf: "flex-start", fontSize: 12, color: "var(--muted)", padding: "2px 4px" }}>Cancel plan</button>
            ))}
          </Section>
        )}
        {cancelling && b && (
          <CancelFlow plan={b.plan} planLabel={b.plan_label ?? b.plan} endsAt={b.renews_at ?? b.ends_at ?? null}
            onClose={() => setCancelling(false)}
            onDone={(msg) => { setCancelling(false); setNotice(msg); void load() }} />
        )}

        {b && (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 12 }}>
            {b.plans.map((p) => {
              const current = b.plan === p.id
              const upgrade = b.enabled && rank(p.id) > rank(b.plan)
              return (
                <div key={p.id} className="h-surface" data-testid={`plan-${p.id}`}
                  style={{ padding: 16, display: "flex", flexDirection: "column", gap: 8,
                    outline: highlight === p.id ? "1.5px solid var(--fg)" : undefined }}>
                  <div className="flex" style={{ justifyContent: "space-between", alignItems: "baseline" }}>
                    <h3 className="h-display" style={{ fontSize: 17, margin: 0 }}>{p.label}</h3>
                    <span style={{ fontSize: 15 }}>{p.price_usd_month ? `$${p.price_usd_month}/mo` : "Free"}</span>
                  </div>
                  <ul className="h-muted" style={{ fontSize: 12, margin: 0, paddingLeft: 16, display: "flex", flexDirection: "column", gap: 3 }}>
                    {p.model_tiers.map((t) => <li key={t}>{TIER_TEXT[t] ?? t}</li>)}
                    <li>Effort up to {p.max_effort}</li>
                    <li>{p.research_allowed ? "Deep research mode" : "No deep research"}</li>
                    <li>About {Math.floor(p.monthly_allowance_usd / perMessage).toLocaleString()} messages a month</li>
                  </ul>
                  <div style={{ marginTop: "auto" }}>
                    {current ? (
                      <span className="h-muted" style={{ fontSize: 12 }}>Your plan</span>
                    ) : upgrade && (p.id === "plus" || p.id === "pro") ? (
                      <>
                        <button className="h-btn-solid" style={{ width: "100%" }} onClick={() => checkout(p.id as "plus" | "pro")}
                          disabled={busy !== null} data-testid={`upgrade-${p.id}`}>
                          {busy === p.id ? "Opening…" : p.id === "plus" && b.trial_days ? `Start ${b.trial_days}-day free trial` : `Upgrade to ${p.label}`}
                        </button>
                        {p.id === "plus" && b.trial_days ? (
                          <p className="h-muted" style={{ fontSize: 11, margin: "6px 0 0" }} data-testid="trial-note">
                            Card needed. Nothing is charged until the trial ends; cancel any time before then.
                          </p>
                        ) : null}
                      </>
                    ) : null}
                  </div>
                </div>
              )
            })}
          </div>
        )}
        {b?.enabled && (
          <p className="h-muted" style={{ fontSize: 11, margin: 0 }}>
            Payments are handled by Dodo Payments, our merchant of record. See the <a href="/refunds" style={{ color: "inherit" }}>Refund Policy</a>. Changes can take a few seconds to show after checkout — <button className="h-btn-ghost" style={{ fontSize: 11, padding: "0 4px" }} onClick={() => void load()}>refresh</button>.
          </p>
        )}
      </div>
    </main>
  )
}

export default function BillingPage() {
  return (
    <Suspense fallback={null}>
      <BillingInner />
    </Suspense>
  )
}
