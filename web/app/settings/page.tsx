"use client"

import { useCallback, useEffect, useState } from "react"
import { useSession } from "next-auth/react"
import { AppHeader } from "@/components/hangul/AppHeader"
import { SignInModal, type AuthMode } from "@/components/hangul/SignInModal"
import { loadAvailableConnectors, type ConnectorInfo } from "@/lib/connectors"
import { deviceTimeZone } from "@/lib/timezone"
import { announcePersona, PERSONAS, type Persona } from "@/lib/personas"
import { PushToggle } from "@/components/hangul/PushToggle"
import { WhatsAppLink } from "@/components/hangul/WhatsAppLink"
import { TaskScheduler, type Task } from "@/components/hangul/TaskScheduler"

/**
 * /settings — how the assistant should treat you (name, tone, timezone,
 * custom instructions) and the questions it asks on your behalf on a
 * schedule. Both are per user; results of scheduled tasks appear in the
 * Chats rail as "⏰ <title>" conversations.
 */

type Prefs = { display_name: string; instructions: string; tone: string; timezone: string; language: string; timezone_auto?: boolean; city?: string; home_address?: string; persona?: string; tones?: string[] }



async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api/${path}`, { ...init, cache: "no-store", headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) } })
  if (!res.ok) {
    let detail = `Request failed (${res.status})`
    try { detail = (await res.json()).detail ?? detail } catch {}
    throw new Error(detail)
  }
  return res.json() as Promise<T>
}


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

export default function SettingsPage() {
  const { status: authStatus } = useSession()
  const [signIn, setSignIn] = useState<{ open: boolean; mode: AuthMode }>({ open: false, mode: "signin" })
  const [gateDismissed, setGateDismissed] = useState(false)
  const signInOpen = signIn.open || (authStatus === "unauthenticated" && !gateDismissed)

  const [prefs, setPrefs] = useState<Prefs | null>(null)
  const [tasks, setTasks] = useState<Task[]>([])
  const [connectors, setConnectors] = useState<ConnectorInfo[]>([])
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  const [busy, setBusy] = useState(false)


  const reload = useCallback(async () => {
    try {
      const [p, t, c] = await Promise.all([api<Prefs>("settings"), api<Task[]>("tasks"), loadAvailableConnectors()])
      setPrefs(p); setTasks(t); setConnectors(c); setError(null)
    } catch (e) { setError((e as Error).message) }
  }, [])

  useEffect(() => {
    if (authStatus !== "authenticated") return
    // Fetch-on-sign-in; state is set after the await (same pattern as ChatsPanel).
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void reload()
  }, [authStatus, reload])

  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true); setError(null)
    try { await fn(); await reload() } catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }

  const savePrefs = () => run(async () => {
    if (!prefs) return
    const { tones: _t, ...body } = prefs
    // automatic = this device's timezone; pinned = what the user typed
    const timezone = body.timezone_auto !== false ? (deviceTimeZone() ?? body.timezone) : body.timezone
    await api("settings", { method: "PUT", body: JSON.stringify({ ...body, timezone, timezone_auto: body.timezone_auto !== false }) })
    announcePersona(PERSONAS.some((x) => x.key === body.persona) ? (body.persona as Persona) : null)
    setSaved(true); setTimeout(() => setSaved(false), 2000)
  })

  // One tap: a daily 08:00 brief, emailed, using whichever Google products exist.
  const addMorningBrief = () => run(async () => {
    const google = connectors.map((c) => c.key).filter((k) => k === "gmail" || k === "calendar")
    await api("tasks", {
      method: "POST",
      body: JSON.stringify({
        // fit_plan: on Free the brief is weekly instead of refused (daily is Plus)
        title: "Morning brief", daily_at: "08:00", connectors: google, mode: "default", deliver_email: true, fit_plan: true,
        question: "Give me my morning brief for today, short and with headings: the weather where I live (use what " +
          "you remember about my city), today's calendar events, my reminders and to-do items, and any important " +
          "unread emails from the last day, and anyone who has been waiting more than a day for my reply. " +
          "Skip any section you can't access.",
      }),
    })
  })

  const browserTz = typeof Intl !== "undefined" ? Intl.DateTimeFormat().resolvedOptions().timeZone : "UTC"

  return (
    <main className="h-has-bottom-nav" style={{ minHeight: "100vh", display: "flex", flexDirection: "column" }}>
      <AppHeader onSignIn={() => setSignIn({ open: true, mode: "signin" })} onSignUp={() => setSignIn({ open: true, mode: "signup" })} />
      <SignInModal open={signInOpen} mode={signIn.mode} onClose={() => { setGateDismissed(true); setSignIn((s) => ({ ...s, open: false })) }} callbackUrl="/settings" reason="Sign in to personalise the assistant." />

      <div style={{ width: "100%", maxWidth: 760, margin: "0 auto", padding: "8px 16px 40px", display: "flex", flexDirection: "column", gap: 16, boxSizing: "border-box" }}>
        <div>
          <h1 className="h-display" style={{ fontSize: 26, margin: "8px 0 4px" }}>Profile & preferences</h1>
          <p className="h-muted" style={{ fontSize: 13, margin: 0 }}>What the assistant knows about how you like to work, and what it does for you while you are away.</p>
        </div>
        {error && <div className="h-surface" style={{ padding: 12, fontSize: 13, color: "var(--err)" }} role="alert">{error}</div>}

        {prefs && (
          <Section title="About you" hint="Goes into every conversation's system prompt. Your instructions are honoured unless they conflict with the assistant's safety rules.">
            <form onSubmit={(e) => { e.preventDefault(); void savePrefs() }} style={{ display: "grid", gap: 8, gridTemplateColumns: "1fr 1fr" }} data-testid="prefs-form">
              <input className="h-input" placeholder="What should it call you?" value={prefs.display_name} onChange={(e) => setPrefs({ ...prefs, display_name: e.target.value })} maxLength={80} aria-label="Display name" />
              <select className="h-input" value={prefs.tone} onChange={(e) => setPrefs({ ...prefs, tone: e.target.value })} aria-label="Tone">
                {(prefs.tones ?? ["concise", "balanced", "detailed"]).map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
              <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                {/* Automatic (the default): follows whatever device the user is on. */}
                <input className="h-input" placeholder={`Timezone, e.g. ${browserTz}`}
                  value={prefs.timezone_auto !== false ? browserTz : prefs.timezone}
                  disabled={prefs.timezone_auto !== false}
                  onChange={(e) => setPrefs({ ...prefs, timezone: e.target.value })} maxLength={64} aria-label="Timezone" list="tz-suggest" />
                <label className="h-muted" style={{ fontSize: 12, display: "flex", alignItems: "center", gap: 6 }}>
                  <input type="checkbox" checked={prefs.timezone_auto !== false} aria-label="Set timezone automatically"
                    onChange={(e) => setPrefs({ ...prefs, timezone_auto: e.target.checked, timezone: e.target.checked ? browserTz : prefs.timezone })} />
                  Set automatically from this device
                </label>
              </div>
              <datalist id="tz-suggest"><option value={browserTz} /><option value="UTC" /></datalist>
              <input className="h-input" placeholder="Preferred language (optional)" value={prefs.language} onChange={(e) => setPrefs({ ...prefs, language: e.target.value })} maxLength={16} aria-label="Language" />
              <input className="h-input" placeholder="Your city (for weather and places near you)" value={prefs.city ?? ""} onChange={(e) => setPrefs({ ...prefs, city: e.target.value })} maxLength={80} aria-label="City" />
              {/* the Today screen's "Leave by": routed with OpenStreetMap, never shown to anyone */}
              <select className="h-input" value={prefs.persona ?? ""} aria-label="What describes you best" data-testid="settings-persona"
                onChange={(e) => setPrefs({ ...prefs, persona: e.target.value })}>
                <option value="">What describes you best? (optional)</option>
                {PERSONAS.map((p) => <option key={p.key} value={p.key}>{p.label}</option>)}
              </select>
              <input id="home" className="h-input" placeholder="Home address (for “leave by” times)" value={prefs.home_address ?? ""}
                onChange={(e) => setPrefs({ ...prefs, home_address: e.target.value })} maxLength={200} aria-label="Home address"
                style={{ gridColumn: "1 / -1" }} data-testid="home-address" />
              <textarea className="h-input" rows={4} placeholder="Custom instructions — e.g. 'I run a small clinic; prefer plain language and always give dates in DD/MM.'" value={prefs.instructions} onChange={(e) => setPrefs({ ...prefs, instructions: e.target.value })} maxLength={2000} style={{ gridColumn: "1 / -1", resize: "vertical" }} aria-label="Custom instructions" />
              <div style={{ gridColumn: "1 / -1", display: "flex", gap: 10, alignItems: "center", justifyContent: "flex-end" }}>
                {saved && <span className="h-muted" style={{ fontSize: 12 }} data-testid="prefs-saved">Saved</span>}
                <button className="h-btn-solid" type="submit" disabled={busy}>Save</button>
              </div>
            </form>
          </Section>
        )}

        <PushToggle frame={(content) => (
          <div id="notifications">
            <Section title="Notifications" hint="Turn them on for each phone or computer you use. Free on every plan.">
              {content}
            </Section>
          </div>
        )} />

        <WhatsAppLink frame={(content) => (
          <div id="whatsapp">
            <Section title="WhatsApp" hint="Hangul on WhatsApp, on Plus and Pro: chat, reminders and your brief, with the same tools and approvals as here. Linking takes one message.">
              {content}
            </Section>
          </div>
        )} />

        <Section title="Scheduled tasks" hint="A question the assistant asks for you on a schedule, with the connectors you pick. Answers appear in your chats (and your inbox, if you choose); anything needing approval waits for you.">
          {prefs && !tasks.some((t) => t.title === "Morning brief") && (
            <div className="h-surface" style={{ padding: "10px 12px", display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }} data-testid="brief-offer">
              <i className="ti ti-sunrise" style={{ fontSize: 18 }} />
              <span style={{ fontSize: 13, flex: 1, minWidth: 200 }}>
                <b>Morning brief</b> — every day at 8:00 AM, an email with your weather, calendar, reminders and important mail.
              </span>
              <button className="h-btn-solid" type="button" disabled={busy} onClick={() => void addMorningBrief()}>Set it up</button>
            </div>
          )}
          <TaskScheduler tasks={tasks} connectors={connectors} busy={busy} run={run} api={api} />
        </Section>
      </div>
    </main>
  )
}
