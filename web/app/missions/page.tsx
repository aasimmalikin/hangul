"use client"

import Link from "next/link"
import { useCallback, useEffect, useState } from "react"
import { useSession } from "next-auth/react"
import { AppHeader } from "@/components/hangul/AppHeader"
import { SignInModal, type AuthMode } from "@/components/hangul/SignInModal"
import { MissionCard, MonthCard, TrustList } from "@/components/hangul/Missions"
import { isRefusal } from "@/lib/brands"
import { missionsApi, type Listing, type Mission } from "@/lib/missions"

/** Missions: the slow days Hangul is handling, what they earned, and the trust given per business. */
export default function MissionsPage() {
  const { status } = useSession()
  const [signIn, setSignIn] = useState<{ open: boolean; mode: AuthMode }>({ open: false, mode: "signin" })
  const [dismissed, setDismissed] = useState(false)
  const [data, setData] = useState<Listing | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    const r = await missionsApi.list()
    if (isRefusal(r)) setError("Couldn't load your missions right now.")
    else { setError(null); setData(r) }
  }, [])

  useEffect(() => {
    if (status !== "authenticated") return
    // Fetch-on-sign-in; state is set after the await.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load()
  }, [status, load])

  const replace = (m: Mission) => setData((d) => d && { ...d, missions: d.missions.map((x) => (x.id === m.id ? { ...x, ...m } : x)) })
  const waiting = data?.missions.filter((m) => m.status === "waiting") ?? []
  const rest = data?.missions.filter((m) => m.status !== "waiting") ?? []

  return (
    <main className="h-has-bottom-nav" style={{ minHeight: "100vh", display: "flex", flexDirection: "column" }}>
      <AppHeader onSignIn={() => setSignIn({ open: true, mode: "signin" })} onSignUp={() => setSignIn({ open: true, mode: "signup" })} />
      <SignInModal open={signIn.open || (status === "unauthenticated" && !dismissed)} mode={signIn.mode}
        onClose={() => { setDismissed(true); setSignIn((s) => ({ ...s, open: false })) }} callbackUrl="/missions"
        reason="Sign in to see what Hangul is handling for you." />
      <div className="h-studio-page" style={{ maxWidth: 760 }}>
        <div className="h-studio-hero">
          <div>
            <h1>Slow days, handled</h1>
            <p>When tomorrow looks slow, Hangul makes the offer post, asks you once, checks how the day went and learns what works for your business.</p>
          </div>
        </div>
        {data && !data.allowed && (
          <div className="h-biz-locked" data-testid="missions-locked">
            <i className="ti ti-lock" /> Hangul handling your slow days is part of Plus.
            <Link className="h-btn-solid" href="/billing?upgrade=plus">See Plus</Link>
          </div>
        )}
        {waiting.map((m) => <MissionCard key={m.id} m={m} onChange={replace} />)}
        {data && <MonthCard r={data.this_month} title="This month" />}
        {data && <MonthCard r={data.last_month} title={`Last month (${data.last_month.label})`} />}
        {rest.map((m) => <MissionCard key={m.id} m={m} onChange={replace} />)}
        {data && <TrustList trust={data.trust} onChange={() => void load()} />}
        {data && data.missions.length === 0 && data.allowed && (
          <div className="h-studio-panel" data-testid="missions-empty">
            <strong>Nothing to handle yet</strong>
            <span className="h-muted">
              Log your sales on <Link href="/business">How&apos;s business</Link>. Once Hangul can forecast your week, it will step in
              the evening before a slow day.
            </span>
          </div>
        )}
        {!data && !error && status === "authenticated" && <span className="h-muted">Loading…</span>}
        {error && <span role="alert" style={{ color: "var(--err)", fontSize: 13 }}>{error}</span>}
      </div>
    </main>
  )
}
