"use client"

import { useCallback, useEffect, useState } from "react"
import { signIn, signOut, useSession } from "next-auth/react"
import { AppHeader } from "@/components/hangul/AppHeader"
import { SignInModal, type AuthMode } from "@/components/hangul/SignInModal"
import { StatusBanner } from "@/components/hangul/StatusBanner"
import { useConnectivity } from "@/components/hangul/useConnectivity"

/**
 * /admin — evals and live numbers for the operator.
 *
 * Authorisation is a chain, and this page only renders what the chain allows:
 *   1. a Google sign-in (verified email) that is recent — checked by the BFF
 *      (`requireAdmin`), which answers 401 `unauthorized` (no session) or
 *      401 `reauth_required` (not Google, or too old) without touching the backend
 *   2. the backend's hard-coded email allowlist + network rule — `/admin/whoami`
 *      answers 200, or 403 `forbidden`
 * The page never learns the allowlist; it only learns whether *this* account
 * passed. Every fetch is `no-store`, bounded by a timeout, and errors are
 * shown with the code the BFF returned so the person knows what to do.
 * Three parts once authorised:
 *   1. the latest report per suite (headline metrics + the CI gate for qa)
 *   2. the eval catalog: what is measured now and what is planned
 *   3. one report in detail, per case, with the tools the agent actually called
 */

type Spec = { key: string; name: string; category: string; status: "available" | "planned"; description: string; metrics: string[]; grader: string; suite: string | null; needs: string }
type Catalog = { suites: Record<string, string>; evals: Spec[] }
type Summary = { suites: Record<string, { available: boolean; n?: number; metrics?: Record<string, number>; prompt_version?: string; model?: string; gate?: { passed: boolean; blocking_failures: string[]; advisory_notes: string[] } }>; running: Record<string, RunStatus> }
type RunStatus = { suite: string; state: "running" | "done" | "failed"; started_at: number; finished_at: number | null; file: string | null; error: string | null }
type RunRow = { file: string; suite: string; created: string; n: number; metrics: Record<string, number>; prompt_version?: string; model?: string }
type CaseRow = { id: string; question?: string; concern?: string; expected_tools?: string[]; tools_called?: string[]; scores: Record<string, number | string[] | string>; trajectory?: Record<string, number | string | null>; answer?: string }
type Report = { suite: string; n: number; metrics: Record<string, number>; prompt_version?: string; model?: string; cases: CaseRow[] }
type Overview = {
  metrics: Record<string, number>
  recent_traces: Array<{ trace_id?: string; model?: string; total_ms?: number; cost_usd?: number; tool_calls?: number; errors?: string[]; question?: string }>
  mcp?: Array<{ name: string; transport: string; state: string; tool_count: number; last_error: string | null }>
  mcp_user_sessions?: Array<{ server: string; subject: string; state: string; last_used: number | null }>
  scheduler?: { enabled: boolean; due_now: number }
}
type SecurityRow = { ts: number; layer: string; severity: string; source: string; action: string; reasons?: string[]; run_id?: string; user_id?: string | number }
type SecuritySummary = { total: number; by_layer: Record<string, number>; by_severity: Record<string, number>; by_action: Record<string, number>; top_sources: Array<[string, number]>; recent: SecurityRow[]; config: { llm_screen: boolean; offender_limit: number } }
type WhoAmI = { authorized: true; email: string; auth_provider: string; auth_at: number; max_auth_age_s: number }
type Gate =
  | { kind: "checking" }
  | { kind: "signed_out" }
  | { kind: "reauth"; detail: string }
  | { kind: "forbidden"; detail: string; email?: string | null }
  | { kind: "error"; detail: string }
  | { kind: "ok"; who: WhoAmI; signedInMinAgo: number }

const mono = { fontFamily: "var(--font-geist-mono)" } as const

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api/admin/${path}`, {
    ...init,
    cache: "no-store",
    signal: init?.signal ?? AbortSignal.timeout(20_000),
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  })
  if (!res.ok) {
    let detail = `Request failed (${res.status})`, code = ""
    try { const j = await res.json(); detail = j.detail ?? detail; code = j.code ?? "" } catch {}
    const err = new Error(detail) as Error & { code?: string; status?: number }
    err.code = code; err.status = res.status
    throw err
  }
  return res.json() as Promise<T>
}

const fmt = (v: unknown) => typeof v === "number" ? (Number.isInteger(v) ? String(v) : v.toFixed(v < 0.01 ? 5 : 2)) : String(v ?? "—")
const pct = (v?: number) => v === undefined ? "—" : `${Math.round(v * 100)}%`
const scoreColor = (v: number) => v >= 0.8 ? "var(--fg)" : v >= 0.5 ? "var(--muted)" : "var(--err)"

function Section({ title, hint, children, right }: { title: string; hint?: string; children: React.ReactNode; right?: React.ReactNode }) {
  return (
    <section className="h-surface" style={{ padding: "18px 20px", display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ display: "flex", alignItems: "flex-start", gap: 12 }}>
        <div style={{ flex: 1 }}>
          <h2 className="h-display" style={{ fontSize: 18, margin: 0 }}>{title}</h2>
          {hint && <p className="h-muted" style={{ fontSize: 12, margin: "4px 0 0" }}>{hint}</p>}
        </div>
        {right}
      </div>
      {children}
    </section>
  )
}

function Metric({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div style={{ minWidth: 110 }}>
      <div className="h-muted" style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: 0.4 }}>{label}</div>
      <div className="h-display" style={{ fontSize: 22, color: tone ?? "var(--fg)" }}>{value}</div>
    </div>
  )
}

/** The Google-only sign-in card the console shows instead of the general modal. */
function GoogleGate({ title, detail, email, action }: { title: string; detail: string; email?: string | null; action: "signin" | "switch" | "none" }) {
  return (
    <div className="h-surface" style={{ padding: "26px 24px", maxWidth: 440, margin: "24px auto 0", textAlign: "center" }} data-testid="admin-gate">
      <i className="ti ti-shield-lock" style={{ fontSize: 28 }} />
      <p className="h-display" style={{ fontSize: 20, margin: "10px 0 6px" }}>{title}</p>
      <p className="h-muted" style={{ fontSize: 13, margin: "0 0 16px" }}>{detail}</p>
      {email && <p className="h-muted" style={{ ...mono, fontSize: 12, margin: "0 0 14px" }}>{email}</p>}
      {action !== "none" && (
        <button
          className="h-btn-solid"
          style={{ width: "100%", justifyContent: "center", gap: 8, padding: 10, fontSize: 14 }}
          // the operator account is rarely the one Google has cached, so always show the chooser
          onClick={() => signIn("google", { redirectTo: "/admin" }, { prompt: "select_account" })}
          data-testid="admin-google"
        >
          <i className="ti ti-brand-google" />
          {action === "switch" ? "Use a different Google account" : "Continue with Google"}
        </button>
      )}
      {action === "switch" && (
        <button className="h-btn-ghost" style={{ marginTop: 8 }} onClick={() => signOut({ redirectTo: "/" })}>Sign out</button>
      )}
    </div>
  )
}

export default function AdminPage() {
  const { data: session, status: authStatus } = useSession()
  const [signIn_, setSignIn] = useState<{ open: boolean; mode: AuthMode }>({ open: false, mode: "signin" })
  const connectivity = useConnectivity()
  const [gateState, setGate] = useState<Gate>({ kind: "checking" })
  // a signed-out visitor is derived from the session, not synced into state
  const gate: Gate = authStatus === "unauthenticated" ? { kind: "signed_out" } : gateState
  const isAdmin = gate.kind === "ok"

  const [catalog, setCatalog] = useState<Catalog | null>(null)
  const [summary, setSummary] = useState<Summary | null>(null)
  const [runs, setRuns] = useState<RunRow[]>([])
  const [report, setReport] = useState<Report | null>(null)
  const [overview, setOverview] = useState<Overview | null>(null)
  const [security, setSecurity] = useState<SecuritySummary | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [limit, setLimit] = useState<number | "">("")

  const reload = useCallback(async () => {
    try {
      const [c, s, r, o, sec] = await Promise.all([
        api<Catalog>("evals?view=catalog"), api<Summary>("evals"), api<RunRow[]>("evals?view=runs"), api<Overview>("overview"),
        api<SecuritySummary>("security"),
      ])
      setCatalog(c); setSummary(s); setRuns(r); setOverview(o); setSecurity(sec); setError(null)
    } catch (e) {
      const err = e as Error & { status?: number; code?: string }
      // the gate can close mid-session (sign-in aged out, allowlist changed): re-run it
      if (err.status === 401 || err.status === 403) setGate({ kind: "checking" })
      else setError(err.message)
    }
  }, [])

  // Step 1 of the chain: who am I to the backend? Runs whenever the session
  // changes and whenever a later call bounces with 401/403.
  useEffect(() => {
    if (authStatus !== "authenticated" || gateState.kind !== "checking") return
    let cancelled = false
    ;(async () => {
      try {
        const who = await api<WhoAmI>("whoami")
        if (!cancelled) setGate({ kind: "ok", who, signedInMinAgo: Math.max(0, Math.round((Date.now() / 1000 - who.auth_at) / 60)) })
      } catch (e) {
        if (cancelled) return
        const err = e as Error & { status?: number; code?: string }
        if (err.code === "reauth_required" || err.code === "unauthorized") setGate({ kind: "reauth", detail: err.message })
        else if (err.status === 403) setGate({ kind: "forbidden", detail: err.message, email: session?.user?.email })
        else setGate({ kind: "error", detail: err.message })
      }
    })()
    return () => { cancelled = true }
  }, [authStatus, gateState.kind, session?.user?.email])

  // Step 2: only an authorised session loads anything.
  useEffect(() => {
    if (!isAdmin) return
    // Fetch-once-authorised; state is set after the await (same pattern as ChatsPanel).
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void reload()
  }, [isAdmin, reload])

  // while a suite is running, poll the summary so the new report appears when it lands
  const running = Object.values(summary?.running ?? {}).some((r) => r.state === "running")
  useEffect(() => {
    if (!running) return
    const t = setInterval(() => { void reload() }, 5_000)
    return () => clearInterval(t)
  }, [running, reload])

  const openReport = async (file: string) => {
    try { setReport(await api<Report>(`evals/runs/${file}`)) } catch (e) { setError((e as Error).message) }
  }

  const startRun = async (suite: string) => {
    if (!confirm(`Run the "${suite}" suite now? This calls the real model and judge and costs money.`)) return
    setBusy(true); setError(null)
    try {
      await api("evals/run", { method: "POST", body: JSON.stringify({ suite, limit: limit === "" ? null : limit }) })
      await reload()
    } catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }

  const available = catalog?.evals.filter((e) => e.status === "available") ?? []
  const planned = catalog?.evals.filter((e) => e.status === "planned") ?? []

  return (
    <main style={{ minHeight: "100vh", display: "flex", flexDirection: "column" }}>
      <AppHeader onSignIn={() => setSignIn({ open: true, mode: "signin" })} onSignUp={() => setSignIn({ open: true, mode: "signup" })} />
      <SignInModal open={signIn_.open} mode={signIn_.mode} onClose={() => setSignIn((s) => ({ ...s, open: false }))} callbackUrl="/admin" />
      <StatusBanner c={connectivity} />

      <div style={{ width: "100%", maxWidth: 960, margin: "0 auto", padding: "8px 16px 40px", display: "flex", flexDirection: "column", gap: 16, boxSizing: "border-box" }}>
        <div>
          <h1 className="h-display" style={{ fontSize: 26, margin: "8px 0 4px" }}>Admin · evals & monitoring</h1>
          <p className="h-muted" style={{ fontSize: 13, margin: 0 }}>How the agent is doing: answer quality, whether it picks the right tools, and what it costs.</p>
        </div>

        {gate.kind === "checking" && <p className="h-muted" style={{ fontSize: 13 }}>Checking your access…</p>}
        {gate.kind === "signed_out" && (
          <GoogleGate title="Operator sign-in" detail="The admin console is restricted to the operator's Google account. Sign in with Google to continue." action="signin" />
        )}
        {gate.kind === "reauth" && (
          <GoogleGate title="Sign in again with Google" detail={gate.detail} email={session?.user?.email} action="switch" />
        )}
        {gate.kind === "forbidden" && (
          <GoogleGate title="Not an administrator" detail={gate.detail} email={gate.email} action="switch" />
        )}
        {gate.kind === "error" && (
          <div className="h-surface" style={{ padding: 12, fontSize: 13, color: "var(--err)" }} role="alert">
            Could not verify access: {gate.detail} <button className="h-btn-ghost" onClick={() => setGate({ kind: "checking" })}>Retry</button>
          </div>
        )}
        {isAdmin && (
          <div className="h-muted" style={{ display: "flex", gap: 10, alignItems: "center", fontSize: 12, flexWrap: "wrap" }} data-testid="admin-identity">
            <i className="ti ti-shield-check" />
            <span>Operator <span style={mono}>{gate.who.email}</span> · Google sign-in {gate.signedInMinAgo} min ago
              (valid {Math.round(gate.who.max_auth_age_s / 3600)} h)</span>
            <button className="h-btn-ghost" style={{ marginLeft: "auto" }} onClick={() => signOut({ redirectTo: "/" })}>Sign out</button>
          </div>
        )}
        {error && <div className="h-surface" style={{ padding: 12, fontSize: 13, color: "var(--err)" }} role="alert">{error}</div>}

        {isAdmin && summary && (
          <>
            <Section title="Latest results" hint="Newest stored report per suite. Runs from here or from `python run_evals.py --suite …`."
              right={
                <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <input className="h-input" type="number" min={1} max={500} placeholder="limit" value={limit} onChange={(e) => setLimit(e.target.value === "" ? "" : Number(e.target.value))} style={{ width: 80 }} aria-label="Case limit" />
                  {Object.keys(catalog?.suites ?? {}).map((suite) => (
                    <button key={suite} className="h-btn-outline" disabled={busy || summary.running[suite]?.state === "running"} onClick={() => void startRun(suite)} data-testid={`run-${suite}`}>
                      {summary.running[suite]?.state === "running" ? `running ${suite}…` : `run ${suite}`}
                    </button>
                  ))}
                </div>
              }>
              {Object.entries(summary.suites).map(([suite, s]) => (
                <div key={suite} style={{ display: "flex", flexDirection: "column", gap: 6 }} data-testid={`suite-${suite}`}>
                  <div style={{ display: "flex", gap: 10, alignItems: "baseline" }}>
                    <span className="h-chip" style={{ cursor: "default" }}>{suite}</span>
                    <span className="h-muted" style={{ fontSize: 12 }}>{catalog?.suites[suite]}</span>
                    {s.gate && <span style={{ marginLeft: "auto", fontSize: 12, color: s.gate.passed ? "var(--fg)" : "var(--err)" }}>{s.gate.passed ? "gate: passing" : "gate: BLOCKED"}</span>}
                  </div>
                  {!s.available ? (
                    <p className="h-muted" style={{ fontSize: 13, margin: 0 }}>No report yet.</p>
                  ) : (
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 18 }}>
                      {Object.entries(s.metrics ?? {}).map(([k, v]) => (
                        <Metric key={k} label={k.replace(/^avg_/, "")} value={k.includes("rate") || (k.startsWith("avg_") && v <= 1 && !k.includes("cost") && !k.includes("steps") && !k.includes("calls")) ? pct(v) : fmt(v)}
                          tone={k.startsWith("avg_") && v <= 1 && !k.includes("cost") && !k.includes("steps") && !k.includes("calls") ? scoreColor(v) : undefined} />
                      ))}
                      <Metric label="cases" value={String(s.n ?? "—")} />
                    </div>
                  )}
                  {s.gate && !s.gate.passed && <ul className="h-muted" style={{ fontSize: 12, margin: 0, paddingLeft: 18 }}>{s.gate.blocking_failures.map((f) => <li key={f}>{f}</li>)}</ul>}
                  {summary.running[suite]?.state === "failed" && <p style={{ fontSize: 12, color: "var(--err)", margin: 0 }}>last run failed: {summary.running[suite].error}</p>}
                </div>
              ))}
            </Section>

            <Section title="Eval catalog" hint="What is measured today, and what is planned next (with what each still needs).">
              <div style={{ display: "grid", gap: 8, gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))" }}>
                {available.map((e) => (
                  <div key={e.key} style={{ border: "0.5px solid var(--surface-border)", borderRadius: 12, padding: "10px 12px", fontSize: 13 }} data-testid={`eval-${e.key}`}>
                    <div style={{ display: "flex", gap: 8, alignItems: "baseline" }}>
                      <strong>{e.name}</strong>
                      <span className="h-muted" style={{ fontSize: 11, marginLeft: "auto" }}>{e.category} · {e.grader}</span>
                    </div>
                    <p className="h-muted" style={{ fontSize: 12, margin: "4px 0 0" }}>{e.description}</p>
                    <div className="h-muted" style={{ ...mono, fontSize: 11, marginTop: 6 }}>{e.suite} → {e.metrics.join(", ")}</div>
                  </div>
                ))}
              </div>
              <details>
                <summary className="h-muted" style={{ cursor: "pointer", fontSize: 13 }}>Planned ({planned.length})</summary>
                <div style={{ display: "grid", gap: 8, gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", marginTop: 10 }}>
                  {planned.map((e) => (
                    <div key={e.key} style={{ border: "0.5px dashed var(--surface-border)", borderRadius: 12, padding: "10px 12px", fontSize: 13, opacity: 0.85 }}>
                      <div style={{ display: "flex", gap: 8, alignItems: "baseline" }}>
                        <strong>{e.name}</strong>
                        <span className="h-muted" style={{ fontSize: 11, marginLeft: "auto" }}>{e.category} · {e.grader}</span>
                      </div>
                      <p className="h-muted" style={{ fontSize: 12, margin: "4px 0 0" }}>{e.description}</p>
                      <div className="h-muted" style={{ fontSize: 11, marginTop: 6 }}>needs: {e.needs}</div>
                    </div>
                  ))}
                </div>
              </details>
            </Section>

            <Section title="Stored runs" hint="Click a run to see every case, its scores and the tools the agent actually called.">
              {runs.length === 0 ? <p className="h-muted" style={{ fontSize: 13, margin: 0 }}>No runs stored under data/eval_runs.</p> : (
                <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "flex", flexDirection: "column", gap: 4, fontSize: 13 }}>
                  {runs.map((r) => (
                    <li key={r.file}>
                      <button className="h-btn-ghost" style={{ width: "100%", justifyContent: "flex-start", gap: 12 }} onClick={() => void openReport(r.file)}>
                        <span className="h-chip" style={{ cursor: "pointer" }}>{r.suite}</span>
                        <span style={{ ...mono, fontSize: 12 }}>{r.created}</span>
                        <span className="h-muted" style={{ fontSize: 12 }}>{r.n} cases · {r.model ?? "?"} · prompt {r.prompt_version ?? "?"}</span>
                        <span className="h-muted" style={{ ...mono, fontSize: 11, marginLeft: "auto" }}>{Object.entries(r.metrics ?? {}).slice(0, 3).map(([k, v]) => `${k.replace(/^avg_/, "")}=${fmt(v)}`).join("  ")}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </Section>

            {report && (
              <Section title={`Report · ${report.suite}`} hint={`${report.n} cases · model ${report.model ?? "?"} · prompt ${report.prompt_version ?? "?"}`}
                right={<button className="h-btn-ghost" onClick={() => setReport(null)}>Close</button>}>
                <div style={{ overflowX: "auto" }}>
                  <table style={{ borderCollapse: "collapse", width: "100%", fontSize: 12 }}>
                    <thead>
                      <tr className="h-muted" style={{ textAlign: "left" }}>
                        <th style={{ padding: "4px 6px" }}>case</th>
                        {Object.keys(report.cases[0]?.scores ?? {}).filter((k) => typeof report.cases[0].scores[k] === "number").map((k) => <th key={k} style={{ padding: "4px 6px" }}>{k.replace(/_/g, " ")}</th>)}
                        <th style={{ padding: "4px 6px" }}>tools called</th>
                        <th style={{ padding: "4px 6px" }}>notes</th>
                      </tr>
                    </thead>
                    <tbody>
                      {report.cases.map((c) => (
                        <tr key={c.id} style={{ borderTop: "0.5px solid var(--surface-border)", verticalAlign: "top" }}>
                          <td style={{ padding: "6px", ...mono }} title={c.question}>{c.id}<div className="h-muted" style={{ fontFamily: "inherit", fontSize: 11 }}>{c.concern}</div></td>
                          {Object.entries(c.scores).filter(([, v]) => typeof v === "number").map(([k, v]) => (
                            <td key={k} style={{ padding: "6px", ...mono, color: scoreColor(v as number) }}>{(v as number).toFixed(2)}</td>
                          ))}
                          <td style={{ padding: "6px", ...mono, fontSize: 11 }}>{(c.tools_called ?? []).join(" → ") || <span className="h-muted">none</span>}{c.expected_tools && <div className="h-muted">want: {c.expected_tools.join(", ") || "none"}</div>}</td>
                          <td className="h-muted" style={{ padding: "6px", fontSize: 11 }}>{((c.scores.notes as string[] | undefined) ?? []).join("; ")}{c.scores.judge_reason ? ` · judge: ${c.scores.judge_reason}` : ""}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Section>
            )}

            <Section title="Prompt-injection defence" hint={`Events from every layer (input screen, tool-result screen, action guard, output guard, uploads). Model screen: ${security?.config.llm_screen ? "on" : "off"} · throttle after ${security?.config.offender_limit ?? "?"} flagged inputs.`}>
              {!security || security.total === 0 ? (
                <p className="h-muted" style={{ fontSize: 13, margin: 0 }} data-testid="security-empty">No security events recorded.</p>
              ) : (
                <>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 18 }} data-testid="security-counts">
                    <Metric label="events" value={String(security.total)} />
                    {Object.entries(security.by_layer).map(([k, v]) => <Metric key={k} label={k} value={String(v)} />)}
                    {Object.entries(security.by_severity).map(([k, v]) => <Metric key={`sev-${k}`} label={`${k} severity`} value={String(v)} tone={k === "high" ? "var(--err)" : undefined} />)}
                    {Object.entries(security.by_action).map(([k, v]) => <Metric key={`act-${k}`} label={k} value={String(v)} />)}
                  </div>
                  {security.top_sources.length > 0 && (
                    <p className="h-muted" style={{ fontSize: 12, margin: 0 }}>Most flagged sources: {security.top_sources.map(([s, n]) => `${s} (${n})`).join(", ")}</p>
                  )}
                  <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "flex", flexDirection: "column", gap: 4, ...mono, fontSize: 12 }}>
                    {security.recent.map((r, i) => (
                      <li key={i} style={{ display: "flex", gap: 10, alignItems: "baseline", flexWrap: "wrap" }}>
                        <span className="h-muted" style={{ width: 150, flexShrink: 0 }}>{new Date(r.ts * 1000).toLocaleString()}</span>
                        <span style={{ color: r.severity === "high" ? "var(--err)" : "var(--fg)", width: 60 }}>{r.severity}</span>
                        <span style={{ width: 90 }}>{r.layer}</span>
                        <span style={{ width: 90 }}>{r.action}</span>
                        <span style={{ width: 130, overflow: "hidden", textOverflow: "ellipsis" }}>{r.source}</span>
                        <span className="h-muted" style={{ flex: 1, minWidth: 200, overflow: "hidden", textOverflow: "ellipsis" }}>{(r.reasons ?? []).join("; ")}</span>
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </Section>

            <Section title="Live" hint="From the running backend: trace ring buffer (resets on restart), MCP servers, per-user Workspace sessions, scheduler.">
              <div style={{ display: "flex", flexWrap: "wrap", gap: 18 }}>
                {Object.entries(overview?.metrics ?? {}).map(([k, v]) => <Metric key={k} label={k} value={fmt(v)} />)}
                {overview?.scheduler && <Metric label="tasks due now" value={overview.scheduler.enabled ? String(overview.scheduler.due_now) : "scheduler off"} />}
              </div>
              {overview?.mcp && overview.mcp.length > 0 && (
                <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }} data-testid="live-mcp">
                  {overview.mcp.map((s) => (
                    <span key={s.name} className="h-chip" style={{ cursor: "default", borderColor: s.state === "failed" ? "var(--err)" : undefined }} title={s.last_error ?? `${s.tool_count} tools`}>
                      <i className={`ti ${s.state === "connected" ? "ti-plug-connected" : s.state === "failed" ? "ti-plug-connected-x" : "ti-plug"}`} style={{ fontSize: 12, marginRight: 5 }} />
                      {s.name} · {s.state}{s.tool_count ? ` · ${s.tool_count}` : ""}
                    </span>
                  ))}
                  {(overview.mcp_user_sessions ?? []).map((u, i) => (
                    <span key={`u-${i}`} className="h-chip h-muted" style={{ cursor: "default" }}>{u.server} · user {u.subject} · {u.state}</span>
                  ))}
                </div>
              )}
              {overview?.recent_traces && overview.recent_traces.length > 0 && (
                <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "flex", flexDirection: "column", gap: 4, ...mono, fontSize: 12 }}>
                  {overview.recent_traces.map((t, i) => (
                    <li key={t.trace_id ?? i} style={{ display: "flex", gap: 10, alignItems: "baseline" }}>
                      <span className="h-muted" style={{ width: 130, flexShrink: 0, overflow: "hidden", textOverflow: "ellipsis" }}>{t.trace_id ?? "—"}</span>
                      <span style={{ width: 90 }}>{t.model ?? "?"}</span>
                      <span style={{ width: 70 }}>{t.total_ms != null ? `${Math.round(t.total_ms)}ms` : "—"}</span>
                      <span style={{ width: 80 }}>{t.cost_usd != null ? `$${t.cost_usd.toFixed(4)}` : "—"}</span>
                      <span style={{ width: 60 }}>{t.tool_calls ?? 0} tools</span>
                      <span style={{ color: t.errors?.length ? "var(--err)" : "var(--muted)" }}>{t.errors?.length ? t.errors.join(", ") : "ok"}</span>
                    </li>
                  ))}
                </ul>
              )}
            </Section>
          </>
        )}
      </div>
    </main>
  )
}
