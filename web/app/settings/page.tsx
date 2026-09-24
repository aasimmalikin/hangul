"use client"

import { useCallback, useEffect, useState } from "react"
import { useSession } from "next-auth/react"
import { AppHeader } from "@/components/hangul/AppHeader"
import { SignInModal, type AuthMode } from "@/components/hangul/SignInModal"
import { loadAvailableConnectors, type ConnectorInfo } from "@/lib/connectors"

/**
 * /settings — how the assistant should treat you (name, tone, timezone,
 * custom instructions) and the questions it asks on your behalf on a
 * schedule. Both are per user; results of scheduled tasks appear in the
 * Chats rail as "⏰ <title>" conversations.
 */

type Prefs = { display_name: string; instructions: string; tone: string; timezone: string; language: string; tones?: string[] }
type Task = { id: number; title: string; question: string; every_minutes: number | null; daily_at: string | null; connectors: string[]; mode: string; enabled: boolean; next_run_at: string | null; last_run_at: string | null; last_status: string; last_run_id: string | null; last_answer: string }

const mono = { fontFamily: "var(--font-geist-mono)" } as const

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api/${path}`, { ...init, cache: "no-store", headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) } })
  if (!res.ok) {
    let detail = `Request failed (${res.status})`
    try { detail = (await res.json()).detail ?? detail } catch {}
    throw new Error(detail)
  }
  return res.json() as Promise<T>
}

const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString() : "—")

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

  const [title, setTitle] = useState("")
  const [question, setQuestion] = useState("")
  const [schedule, setSchedule] = useState<"daily" | "interval">("daily")
  const [dailyAt, setDailyAt] = useState("08:00")
  const [every, setEvery] = useState(60)
  const [taskConnectors, setTaskConnectors] = useState<string[]>([])
  const [research, setResearch] = useState(false)

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
    await api("settings", { method: "PUT", body: JSON.stringify(body) })
    setSaved(true); setTimeout(() => setSaved(false), 2000)
  })

  const addTask = () => run(async () => {
    await api("tasks", {
      method: "POST",
      body: JSON.stringify({
        title, question, connectors: taskConnectors, mode: research ? "research" : "default",
        ...(schedule === "daily" ? { daily_at: dailyAt } : { every_minutes: every }),
      }),
    })
    setTitle(""); setQuestion("")
  })

  const browserTz = typeof Intl !== "undefined" ? Intl.DateTimeFormat().resolvedOptions().timeZone : "UTC"

  return (
    <main style={{ minHeight: "100vh", display: "flex", flexDirection: "column" }}>
      <AppHeader onSignIn={() => setSignIn({ open: true, mode: "signin" })} onSignUp={() => setSignIn({ open: true, mode: "signup" })} />
      <SignInModal open={signInOpen} mode={signIn.mode} onClose={() => { setGateDismissed(true); setSignIn((s) => ({ ...s, open: false })) }} callbackUrl="/settings" reason="Sign in to personalise the assistant." />

      <div style={{ width: "100%", maxWidth: 760, margin: "0 auto", padding: "8px 16px 40px", display: "flex", flexDirection: "column", gap: 16, boxSizing: "border-box" }}>
        <div>
          <h1 className="h-display" style={{ fontSize: 26, margin: "8px 0 4px" }}>Personalisation & tasks</h1>
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
              <input className="h-input" placeholder={`Timezone, e.g. ${browserTz}`} value={prefs.timezone} onChange={(e) => setPrefs({ ...prefs, timezone: e.target.value })} maxLength={64} aria-label="Timezone" list="tz-suggest" />
              <datalist id="tz-suggest"><option value={browserTz} /><option value="UTC" /></datalist>
              <input className="h-input" placeholder="Preferred language (optional)" value={prefs.language} onChange={(e) => setPrefs({ ...prefs, language: e.target.value })} maxLength={16} aria-label="Language" />
              <textarea className="h-input" rows={4} placeholder="Custom instructions — e.g. 'I run a small clinic; prefer plain language and always give dates in DD/MM.'" value={prefs.instructions} onChange={(e) => setPrefs({ ...prefs, instructions: e.target.value })} maxLength={2000} style={{ gridColumn: "1 / -1", resize: "vertical" }} aria-label="Custom instructions" />
              <div style={{ gridColumn: "1 / -1", display: "flex", gap: 10, alignItems: "center", justifyContent: "flex-end" }}>
                {saved && <span className="h-muted" style={{ fontSize: 12 }} data-testid="prefs-saved">Saved</span>}
                <button className="h-btn-solid" type="submit" disabled={busy}>Save</button>
              </div>
            </form>
          </Section>
        )}

        <Section title="Scheduled tasks" hint="A question the assistant asks for you on a schedule, with the connectors you pick. Answers appear in your chats; anything needing approval waits for you.">
          <form onSubmit={(e) => { e.preventDefault(); void addTask() }} style={{ display: "grid", gap: 8, gridTemplateColumns: "1fr 1fr" }} data-testid="task-form">
            <input className="h-input" placeholder="Title, e.g. Morning brief" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={120} required aria-label="Task title" />
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <select className="h-input" style={{ width: "auto" }} value={schedule} onChange={(e) => setSchedule(e.target.value as "daily" | "interval")} aria-label="Schedule kind">
                <option value="daily">Every day at</option>
                <option value="interval">Every N minutes</option>
              </select>
              {schedule === "daily"
                ? <input className="h-input" type="time" value={dailyAt} onChange={(e) => setDailyAt(e.target.value)} aria-label="Time of day" />
                : <input className="h-input" type="number" min={15} max={10080} value={every} onChange={(e) => setEvery(Number(e.target.value))} aria-label="Minutes" />}
            </div>
            <textarea className="h-input" rows={2} placeholder="What should it do? e.g. 'Summarise unread email from today and list meetings tomorrow.'" value={question} onChange={(e) => setQuestion(e.target.value)} maxLength={4000} required style={{ gridColumn: "1 / -1", resize: "vertical" }} aria-label="Task question" />
            <div style={{ gridColumn: "1 / -1", display: "flex", gap: 12, flexWrap: "wrap", alignItems: "center" }}>
              {connectors.map((c) => (
                <label key={c.key} className="h-muted" style={{ fontSize: 12, display: "flex", gap: 6, alignItems: "center" }}>
                  <input type="checkbox" checked={taskConnectors.includes(c.key)} onChange={(e) => setTaskConnectors((ks) => e.target.checked ? [...ks, c.key] : ks.filter((k) => k !== c.key))} /> {c.label}
                </label>
              ))}
              <label className="h-muted" style={{ fontSize: 12, display: "flex", gap: 6, alignItems: "center" }}>
                <input type="checkbox" checked={research} onChange={(e) => setResearch(e.target.checked)} /> deep research
              </label>
              <button className="h-btn-solid" type="submit" disabled={busy || !title || !question} style={{ marginLeft: "auto" }}>Add task</button>
            </div>
          </form>

          {tasks.length === 0 ? <p className="h-muted" style={{ fontSize: 13, margin: 0 }}>No scheduled tasks.</p> : (
            <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "flex", flexDirection: "column", gap: 10 }}>
              {tasks.map((t) => (
                <li key={t.id} style={{ border: "0.5px solid var(--surface-border)", borderRadius: 12, padding: "10px 12px", fontSize: 13 }} data-testid={`task-${t.id}`}>
                  <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
                    <strong>{t.title}</strong>
                    <span className="h-muted" style={{ fontSize: 12 }}>{t.daily_at ? `daily at ${t.daily_at}` : `every ${t.every_minutes} min`}{t.connectors.length ? ` · ${t.connectors.join(", ")}` : ""}{t.mode === "research" ? " · research" : ""}</span>
                    <span className="h-muted" style={{ ...mono, fontSize: 11, marginLeft: "auto" }}>{t.enabled ? `next ${when(t.next_run_at)}` : "paused"} · last: {t.last_status}</span>
                  </div>
                  <div className="h-muted" style={{ fontSize: 12, marginTop: 4 }}>{t.question}</div>
                  {t.last_answer && <div style={{ fontSize: 12, marginTop: 6, whiteSpace: "pre-wrap" }}>{t.last_answer.slice(0, 400)}{t.last_answer.length > 400 ? "…" : ""}</div>}
                  {t.last_status === "needs_approval" && t.last_run_id && (
                    <div className="h-surface" style={{ padding: "8px 10px", marginTop: 8, fontSize: 12, display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }} data-testid={`task-${t.id}-approval`}>
                      <i className="ti ti-hand-stop" />
                      <span style={{ flex: 1 }}>This run wants to do something that needs your approval.</span>
                      <button className="h-btn-solid" disabled={busy} onClick={() => run(() => api("approve", { method: "POST", body: JSON.stringify({ approval_id: t.last_run_id, decision: "approve" }) }))}>Approve</button>
                      <button className="h-btn-outline" disabled={busy} onClick={() => run(() => api("approve", { method: "POST", body: JSON.stringify({ approval_id: t.last_run_id, decision: "reject" }) }))}>Reject</button>
                    </div>
                  )}
                  <div style={{ display: "flex", gap: 6, marginTop: 8 }}>
                    <button className="h-btn-ghost" disabled={busy} onClick={() => run(() => api(`tasks/${t.id}/run`, { method: "POST" }))}>Run now</button>
                    <button className="h-btn-ghost" disabled={busy} onClick={() => run(() => api(`tasks/${t.id}`, { method: "POST", body: JSON.stringify({ enabled: !t.enabled }) }))}>{t.enabled ? "Pause" : "Resume"}</button>
                    <button className="h-btn-ghost" disabled={busy} onClick={() => run(() => api(`tasks/${t.id}`, { method: "DELETE" }))}>Delete</button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Section>
      </div>
    </main>
  )
}
