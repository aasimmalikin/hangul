"use client"

import { useCallback, useEffect, useState } from "react"
import { signIn as authSignIn, useSession } from "next-auth/react"
import { GOOGLE_WORKSPACE_SCOPES, loadIntegrations } from "@/lib/connectors"
import { deviceTimeZone } from "@/lib/timezone"

/**
 * The first-run walkthrough: three short steps, each skippable, so Today is
 * useful on day one.
 *   1. What should I call you? (+ city; the timezone is detected)
 *   2. Connect Google? (Gmail + Calendar make the brief and reminders shine)
 *   3. A morning brief every day at 8:00? (weekly on the Free plan; daily is Plus)
 * Shown once: finishing or skipping calls POST /api/settings/onboarded. The
 * current step survives the Google sign-in round trip (sessionStorage).
 */

const STEP_KEY = "hangul:onboarding-step"
type Settings = Record<string, unknown> & { display_name?: string; city?: string; onboarded?: boolean; tones?: string[] }

async function saveSettings(patch: Partial<Settings>) {
  const cur: Settings | null = await fetch("/api/settings", { cache: "no-store" }).then((r) => (r.ok ? r.json() : null)).catch(() => null)
  if (!cur) return
  const body: Settings = { ...cur, ...patch }
  delete body.tones
  await fetch("/api/settings", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
}

export function Onboarding() {
  const { data: session } = useSession()
  const [open, setOpen] = useState(false)
  const [step, setStep] = useState(1)
  const [name, setName] = useState("")
  const [city, setCity] = useState("")
  const [google, setGoogle] = useState(false)
  const [busy, setBusy] = useState(false)
  const [weeklyOnly, setWeeklyOnly] = useState(false)     // Free plan with billing on: the brief is weekly

  useEffect(() => {
    let alive = true
    void fetch("/api/settings", { cache: "no-store" }).then((r) => (r.ok ? r.json() : null)).then((s: Settings | null) => {
      if (!alive || !s || s.onboarded !== false) return
      let saved = 1
      try { saved = Number(sessionStorage.getItem(STEP_KEY)) || 1 } catch { /* private mode */ }
      setStep(Math.min(Math.max(saved, 1), 3))
      setName(String(s.display_name || "") || (session?.user?.name ?? "").split(" ")[0] || "")
      setCity(String(s.city || ""))
      setOpen(true)
    }).catch(() => {})
    void loadIntegrations().then((i) => { if (alive) setGoogle(Boolean(i?.google.connected)) })
    void fetch("/api/billing", { cache: "no-store" }).then((r) => (r.ok ? r.json() : null))
      .then((b: { enabled?: boolean; plan?: string } | null) => { if (alive) setWeeklyOnly(Boolean(b?.enabled && b.plan === "free")) })
      .catch(() => {})
    return () => { alive = false }
    // runs once per page load; the session name is only a default
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const go = useCallback((n: number) => {
    setStep(n)
    try { sessionStorage.setItem(STEP_KEY, String(n)) } catch { /* ignore */ }
  }, [])

  const finish = async () => {
    setBusy(true)
    await fetch("/api/settings/onboarded", { method: "POST" }).catch(() => null)
    try { sessionStorage.removeItem(STEP_KEY) } catch { /* ignore */ }
    setOpen(false)
    setBusy(false)
    window.dispatchEvent(new Event("hangul:refresh-today"))
  }

  if (!open) return null

  const step1 = async () => {
    setBusy(true)
    await saveSettings({ display_name: name.trim(), city: city.trim(), timezone: deviceTimeZone() ?? "UTC", timezone_auto: true })
    setBusy(false)
    go(2)
  }
  const connectGoogle = () => {
    go(3)                                         // where to resume after Google sends the user back
    void authSignIn("google", { redirectTo: "/" },
      { scope: GOOGLE_WORKSPACE_SCOPES, access_type: "offline", prompt: "consent", include_granted_scopes: "true" })
  }
  const morningBrief = async () => {
    setBusy(true)
    await fetch("/api/tasks", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        // fit_plan: on Free the brief is weekly instead of refused (daily is Plus)
        title: "Morning brief", daily_at: "08:00", connectors: google ? ["gmail", "calendar"] : [], mode: "default", deliver_email: true, fit_plan: true,
        question: "Give me my morning brief for today, short and with headings: the weather where I live, today's calendar " +
          "events, my reminders and to-do items, and any important unread emails from the last day. Skip any section you can't access.",
      }),
    }).catch(() => null)
    await finish()
  }

  const dots = (
    <div style={{ display: "flex", gap: 6, justifyContent: "center" }} aria-hidden>
      {[1, 2, 3].map((n) => (
        <span key={n} style={{ width: n === step ? 18 : 6, height: 6, borderRadius: 999, transition: "width 150ms",
          background: n <= step ? "var(--fg)" : "var(--surface-border)" }} />
      ))}
    </div>
  )

  return (
    <div role="dialog" aria-modal="true" aria-label="Welcome to Hangul" data-testid="onboarding"
      style={{ position: "fixed", inset: 0, zIndex: 70, background: "var(--scrim)", display: "grid", placeItems: "center", padding: 16 }}>
      <div className="h-popover" style={{ width: "100%", maxWidth: 420, padding: "22px 22px 18px", display: "flex", flexDirection: "column", gap: 14 }}>
        {dots}
        {step === 1 && (
          <form onSubmit={(e) => { e.preventDefault(); void step1() }} style={{ display: "flex", flexDirection: "column", gap: 10 }} data-testid="onboarding-1">
            <h2 className="h-display" style={{ fontSize: 22, margin: 0, textAlign: "center" }}>Welcome to Hangul</h2>
            <p className="h-muted" style={{ fontSize: 13, margin: 0, textAlign: "center" }}>Two quick questions so I can help from day one.</p>
            <input className="h-input" placeholder="What should I call you?" value={name} onChange={(e) => setName(e.target.value)} maxLength={80} aria-label="Your name" autoFocus />
            <input className="h-input" placeholder="Your city (for weather and places near you)" value={city} onChange={(e) => setCity(e.target.value)} maxLength={80} aria-label="Your city" />
            <span className="h-muted" style={{ fontSize: 11 }}>Timezone: {deviceTimeZone() ?? "UTC"} (from this device)</span>
            <button className="h-btn-solid" type="submit" disabled={busy}>Continue</button>
          </form>
        )}
        {step === 2 && (
          <div style={{ display: "flex", flexDirection: "column", gap: 10, textAlign: "center" }} data-testid="onboarding-2">
            <i className="ti ti-brand-google" style={{ fontSize: 30 }} />
            <h2 className="h-display" style={{ fontSize: 20, margin: 0 }}>Connect Google?</h2>
            <p className="h-muted" style={{ fontSize: 13, margin: 0 }}>
              Then I can read your calendar and email, find free time and draft replies. I always ask before sending or changing anything.
            </p>
            {google ? (
              <button className="h-btn-solid" onClick={() => go(3)}>Connected ✓ — continue</button>
            ) : (
              <>
                <button className="h-btn-solid" onClick={connectGoogle} data-testid="onboarding-google">Connect Google</button>
                <button className="h-btn-ghost" onClick={() => go(3)}>Not now</button>
              </>
            )}
          </div>
        )}
        {step === 3 && (
          <div style={{ display: "flex", flexDirection: "column", gap: 10, textAlign: "center" }} data-testid="onboarding-3">
            <i className="ti ti-sunrise" style={{ fontSize: 30 }} />
            <h2 className="h-display" style={{ fontSize: 20, margin: 0 }}>A morning brief?</h2>
            <p className="h-muted" style={{ fontSize: 13, margin: 0 }}>
              {weeklyOnly ? "Once a week" : "Every day"} at 8:00 I&apos;ll email you the weather, your day&apos;s events, reminders{google ? " and important mail" : ""}.
            </p>
            {weeklyOnly && <p className="h-muted" style={{ fontSize: 12, margin: 0 }} data-testid="onboarding-brief-weekly">On Free it comes once a week. Plus sends it every morning.</p>}
            <button className="h-btn-solid" onClick={() => void morningBrief()} disabled={busy} data-testid="onboarding-brief">{weeklyOnly ? "Yes, weekly" : "Yes, every morning"}</button>
            <button className="h-btn-ghost" onClick={() => void finish()} disabled={busy}>Not now</button>
          </div>
        )}
        <button className="h-btn-ghost" onClick={() => void finish()} disabled={busy} style={{ fontSize: 11, alignSelf: "center", color: "var(--muted)" }} data-testid="onboarding-skip">
          Skip for now
        </button>
      </div>
    </div>
  )
}
