"use client"

import Link from "next/link"
import { use, useCallback, useEffect, useState } from "react"
import { useSession } from "next-auth/react"
import { AppHeader } from "@/components/hangul/AppHeader"
import { SignInModal, type AuthMode } from "@/components/hangul/SignInModal"
import { MissionCard } from "@/components/hangul/Missions"
import { isRefusal } from "@/lib/brands"
import { missionsApi, type Mission } from "@/lib/missions"

/** One mission: its checklist, the post, the go-ahead, undo and the result (where push and WhatsApp links open). */
export default function MissionPage({ params }: { params: Promise<{ id: string }> }) {
  const { id: raw } = use(params)
  const id = Number(raw)
  const { status } = useSession()
  const [signIn, setSignIn] = useState<{ open: boolean; mode: AuthMode }>({ open: false, mode: "signin" })
  const [dismissed, setDismissed] = useState(false)
  const [m, setM] = useState<Mission | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    const r = await missionsApi.get(id)
    if (isRefusal(r)) setError(r.detail)
    else { setError(null); setM(r) }
  }, [id])

  useEffect(() => {
    if (status !== "authenticated" || !Number.isFinite(id)) return
    // Fetch-on-sign-in; state is set after the await.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load()
  }, [status, id, load])

  return (
    <main className="h-has-bottom-nav" style={{ minHeight: "100vh", display: "flex", flexDirection: "column" }}>
      <AppHeader onSignIn={() => setSignIn({ open: true, mode: "signin" })} onSignUp={() => setSignIn({ open: true, mode: "signup" })} />
      <SignInModal open={signIn.open || (status === "unauthenticated" && !dismissed)} mode={signIn.mode}
        onClose={() => { setDismissed(true); setSignIn((s) => ({ ...s, open: false })) }} callbackUrl={`/missions/${raw}`}
        reason="Sign in to see this slow day." />
      <div className="h-studio-page" style={{ maxWidth: 760 }}>
        <Link href="/missions" className="h-muted" style={{ fontSize: 13 }}><i className="ti ti-chevron-left" /> All slow days</Link>
        {/* a decision answers with the mission minus can_undo/trust, so read it again for those */}
        {m && <MissionCard m={m} full onChange={() => void load()} />}
        {!m && !error && status === "authenticated" && <span className="h-muted">Loading…</span>}
        {error && <span role="alert" style={{ color: "var(--err)", fontSize: 13 }}>{error}</span>}
      </div>
    </main>
  )
}
