"use client"

import { useCallback, useEffect, useState } from "react"
import { useSession } from "next-auth/react"
import { AppHeader } from "@/components/hangul/AppHeader"
import { SignInModal, type AuthMode } from "@/components/hangul/SignInModal"
import { BusinessDashboard, BusinessSetup } from "@/components/hangul/Business"
import { businessApi, isRefusal, type Listing, type Overview } from "@/lib/business"

/** How's business: the user's business (or the first of several), set up once, then the daily dashboard. */
export default function BusinessPage() {
  const { status } = useSession()
  const [signIn, setSignIn] = useState<{ open: boolean; mode: AuthMode }>({ open: false, mode: "signin" })
  const [dismissed, setDismissed] = useState(false)
  const [listing, setListing] = useState<Listing | null>(null)
  const [current, setCurrent] = useState<number | null>(null)
  const [ov, setOv] = useState<Overview | null>(null)
  const [adding, setAdding] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const loadList = useCallback(async () => {
    const r = await businessApi.list()
    if (isRefusal(r)) { setError("Couldn't load your business right now."); return }
    setListing(r)
    setCurrent((c) => c ?? r.businesses.find((b) => !b.paused)?.id ?? null)
  }, [])

  const loadOverview = useCallback(async (id: number) => {
    const r = await businessApi.overview(id)
    if (isRefusal(r)) setError(r.detail)
    else { setError(null); setOv(r) }
  }, [])

  useEffect(() => {
    if (status !== "authenticated") return
    // Fetch-on-sign-in; state is set after the await.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadList()
  }, [status, loadList])

  useEffect(() => {
    if (current === null) return
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadOverview(current)
  }, [current, loadOverview])

  const usable = listing?.businesses.filter((b) => !b.paused) ?? []
  const showSetup = listing && (adding || usable.length === 0)
  return (
    <main className="h-has-bottom-nav" style={{ minHeight: "100vh", display: "flex", flexDirection: "column" }}>
      <AppHeader onSignIn={() => setSignIn({ open: true, mode: "signin" })} onSignUp={() => setSignIn({ open: true, mode: "signup" })} />
      <SignInModal open={signIn.open || (status === "unauthenticated" && !dismissed)} mode={signIn.mode}
        onClose={() => { setDismissed(true); setSignIn((s) => ({ ...s, open: false })) }} callbackUrl="/business"
        reason="Sign in to see how business is going." />
      <div className="h-studio-page">
        <div className="h-studio-hero">
          <div>
            <h1>How&apos;s business</h1>
            <p>{ov && !showSetup ? ov.business.name : "Tell Hangul each day's sales. It learns your week, warns you before a slow day, and helps you fix it."}</p>
          </div>
          {listing && usable.length > 0 && !showSetup && (
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              {usable.length > 1 && (
                <select className="h-input" style={{ width: "auto" }} value={current ?? ""} aria-label="Business"
                  onChange={(e) => { setOv(null); setCurrent(Number(e.target.value)) }}>
                  {usable.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
                </select>
              )}
              {listing.can_add && <button className="h-btn-ghost" onClick={() => setAdding(true)} data-testid="biz-add">+ Another business</button>}
            </div>
          )}
        </div>
        {showSetup && (
          <BusinessSetup listing={listing} onSaved={(b) => { setAdding(false); setOv(null); setCurrent(b.id); void loadList() }} />
        )}
        {!showSetup && ov && <BusinessDashboard ov={ov} onChange={() => current !== null && void loadOverview(current)} />}
        {!showSetup && !ov && !error && status === "authenticated" && <span className="h-muted">Looking at your week…</span>}
        {error && <span role="alert" style={{ color: "var(--err)", fontSize: 13 }}>{error}</span>}
      </div>
    </main>
  )
}
