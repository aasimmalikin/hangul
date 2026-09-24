"use client"

import { useCallback, useEffect, useState } from "react"
import { signIn as authSignIn, useSession } from "next-auth/react"
import { GOOGLE_WORKSPACE_SCOPES, loadIntegrations, type Integrations } from "@/lib/connectors"
import { AppHeader } from "@/components/hangul/AppHeader"
import { SignInModal, type AuthMode } from "@/components/hangul/SignInModal"

/**
 * /vault — the user's third-party credentials and what the agent may do with
 * them. Secrets are typed once, sent straight to the backend, and never come
 * back: the list shows a label and a fingerprint. Consent is what actually
 * lets the agent use a credential; revoking either one takes effect on the
 * agent's next call.
 */

type Provider = { name: string; base_url: string; inject: string; description: string; system_credential: boolean }
type Credential = { id: number; provider: string; label: string; kind: string; fingerprint: string; system: boolean; created_at: string | null; expires_at: string | null; revoked_at: string | null }
type Consent = { id: number; provider: string; credential_id: number | null; allow_write: boolean; granted_at: string | null; expires_at: string; revoked_at: string | null }
type AuditRow = { ts: number; provider: string; method: string; path: string; status: number; ms: number; denied?: string }

const mono = { fontFamily: "var(--font-geist-mono)" } as const

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api/vault/${path}`, { ...init, headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) } })
  if (!res.ok) {
    let detail = `Request failed (${res.status})`
    try { detail = (await res.json()).detail ?? detail } catch {}
    throw new Error(detail)
  }
  return res.json() as Promise<T>
}

function when(iso: string | null | undefined) {
  if (!iso) return "—"
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString()
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

export default function VaultPage() {
  const { status: authStatus } = useSession()
  const [signIn, setSignIn] = useState<{ open: boolean; mode: AuthMode }>({ open: false, mode: "signin" })
  const [gateDismissed, setGateDismissed] = useState(false)
  // signed-out visitors see the sign-in modal until they dismiss it; derived, not synced
  const signInOpen = signIn.open || (authStatus === "unauthenticated" && !gateDismissed)

  const [providers, setProviders] = useState<Provider[]>([])
  const [credentials, setCredentials] = useState<Credential[]>([])
  const [consents, setConsents] = useState<Consent[]>([])
  const [audit, setAudit] = useState<AuditRow[]>([])
  const [integrations, setIntegrations] = useState<Integrations | null>(null)
  const [check, setCheck] = useState<{ token: unknown; servers: Array<{ name: string; status: number | null; body: string }>; sdk?: { exchanges: Array<{ method: string; url: string; status?: number; content_type?: string; request?: string; response?: string }>; initialize?: unknown; tools?: string[]; error?: string; call?: { tool: string; arguments: unknown; is_error?: boolean; preview?: string; content_types?: string[]; exception?: string } } } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [unavailable, setUnavailable] = useState(false)

  // add-credential form
  const [provider, setProvider] = useState("github")
  const [label, setLabel] = useState("")
  const [secret, setSecret] = useState("")
  const [baseUrl, setBaseUrl] = useState("")
  // consent form
  const [consentProvider, setConsentProvider] = useState("")
  const [ttlHours, setTtlHours] = useState(24)
  const [allowWrite, setAllowWrite] = useState(false)

  const reload = useCallback(async () => {
    // Google Workspace status does not depend on the vault being configured
    setIntegrations(await loadIntegrations())
    try {
      const [p, c, s, a] = await Promise.all([
        api<Provider[]>("providers"), api<Credential[]>("credentials"),
        api<Consent[]>("consents"), api<AuditRow[]>("audit"),
      ])
      setProviders(p); setCredentials(c); setConsents(s); setAudit(a); setUnavailable(false); setError(null)
    } catch (e) {
      const msg = (e as Error).message
      if (/not configured|503/.test(msg)) setUnavailable(true)
      else setError(msg)
    }
  }, [])

  useEffect(() => {
    if (authStatus !== "authenticated") return
    // Fetch-on-sign-in; state is set after the await, not synchronously in
    // the effect body (same pattern as ChatsPanel).
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void reload()
  }, [authStatus, reload])

  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true); setError(null)
    try { await fn(); await reload() } catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }

  const addCredential = () => run(async () => {
    const custom = provider === "__custom__"
    await api("credentials", {
      method: "POST",
      body: JSON.stringify({
        provider: custom ? "http" : provider, label, secret,
        base_url: custom && baseUrl ? baseUrl : undefined,
      }),
    })
    setSecret(""); setLabel(""); setBaseUrl("")
  })

  const grantConsent = () => run(() => api("consents", {
    method: "POST", body: JSON.stringify({ provider: chosenConsentProvider, ttl_hours: ttlHours, allow_write: allowWrite }),
  }))

  const activeCredentials = credentials.filter((c) => !c.revoked_at)
  const activeConsents = consents.filter((c) => !c.revoked_at && new Date(c.expires_at) > new Date())
  const consentable = Array.from(new Set([
    ...activeCredentials.map((c) => c.provider),
    ...providers.filter((p) => p.system_credential).map((p) => p.name),
  ]))
  // first consentable provider is the default until the user picks one
  const chosenConsentProvider = consentProvider || consentable[0] || ""

  return (
    <main style={{ minHeight: "100vh", display: "flex", flexDirection: "column" }}>
      <AppHeader onSignIn={() => setSignIn({ open: true, mode: "signin" })} onSignUp={() => setSignIn({ open: true, mode: "signup" })} />
      <SignInModal open={signInOpen} mode={signIn.mode} onClose={() => { setGateDismissed(true); setSignIn((s) => ({ ...s, open: false })) }} callbackUrl="/vault" reason="Sign in to manage your connected services." />

      <div style={{ width: "100%", maxWidth: 760, margin: "0 auto", padding: "8px 16px 40px", display: "flex", flexDirection: "column", gap: 16, boxSizing: "border-box" }}>
        <div>
          <h1 className="h-display" style={{ fontSize: 26, margin: "8px 0 4px" }}>Token vault</h1>
          <p className="h-muted" style={{ fontSize: 13, margin: 0 }}>
            The agent never sees your keys. It asks the vault for a short-lived grant and every request is
            proxied with the real credential injected server-side. Reads run under the consent you give here;
            every write still asks you first.
          </p>
        </div>

        {unavailable && (
          <div className="h-surface" style={{ padding: 14, fontSize: 13 }}>
            The vault is not configured on this server (<code style={mono}>VAULT_MASTER_KEY</code> is unset).
          </div>
        )}
        {error && (
          <div className="h-surface" style={{ padding: 12, fontSize: 13, color: "var(--err)" }} role="alert">{error}</div>
        )}

        <Section title="Google Workspace" hint="Gmail, Calendar, Drive and Docs through Google's own MCP servers, on your account. Reads run when the connector is on; sending, creating, changing or deleting always asks you first.">
          <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }} data-testid="google-workspace">
            <i className="ti ti-brand-google" style={{ fontSize: 22 }} />
            <div style={{ flex: 1, minWidth: 200, fontSize: 13 }}>
              {integrations?.google.connected ? (
                <>Connected · {integrations.google.products.length ? integrations.google.products.join(", ") : "no Workspace scopes yet"}</>
              ) : (
                <span className="h-muted">Not connected. Connecting re-runs Google sign-in asking for Workspace access; you can revoke it any time.</span>
              )}
            </div>
            <button className="h-btn-solid" onClick={() => authSignIn("google", { redirectTo: "/vault" }, { scope: GOOGLE_WORKSPACE_SCOPES, access_type: "offline", prompt: "consent", include_granted_scopes: "true" })} data-testid="google-connect">
              {integrations?.google.connected ? "Reconnect / change access" : "Connect Google Workspace"}
            </button>
            {integrations?.google.connected && (
              <button className="h-btn-outline" disabled={busy} data-testid="google-check"
                onClick={() => run(async () => {
                  const r = await fetch("/api/integrations/google/check", { cache: "no-store", signal: AbortSignal.timeout(45_000) })
                  if (!r.ok) throw new Error(`Check failed (${r.status})`)
                  setCheck(await r.json())
                })}>Test connection</button>
            )}
            {integrations?.google.connected && (
              <button className="h-btn-ghost" disabled={busy} data-testid="google-disconnect"
                onClick={() => run(async () => { await fetch("/api/integrations/google", { method: "DELETE" }) })}>Disconnect</button>
            )}
          </div>
          {check && (
            <div style={{ ...mono, fontSize: 12, display: "flex", flexDirection: "column", gap: 4 }} data-testid="google-check-result">
              <div>token: {typeof check.token === "string" ? check.token : JSON.stringify(check.token)}</div>
              {check.servers.map((s) => (
                <div key={s.name} style={{ color: s.status && s.status < 300 ? "var(--fg)" : "var(--err)", wordBreak: "break-all" }}>
                  {s.name}: HTTP {s.status ?? "—"} · {s.body}
                </div>
              ))}
              {check.sdk && (
                <div style={{ marginTop: 6 }}>
                  <div>sdk handshake (gmail): {check.sdk.error ? <span style={{ color: "var(--err)" }}>{check.sdk.error}</span> : `ok · ${(check.sdk.tools ?? []).length} tools: ${(check.sdk.tools ?? []).join(", ")}`}</div>
                  {check.sdk.call && (
                    <div style={{ color: check.sdk.call.exception || check.sdk.call.is_error ? "var(--err)" : "var(--fg)", wordBreak: "break-all" }}>
                      call {check.sdk.call.tool}({JSON.stringify(check.sdk.call.arguments)}) → {check.sdk.call.exception ?? (check.sdk.call.is_error ? `tool error: ${check.sdk.call.preview}` : `ok (${(check.sdk.call.content_types ?? []).join(",")}): ${check.sdk.call.preview}`)}
                    </div>
                  )}
                  {check.sdk.exchanges.map((x, i) => (
                    <div key={i} style={{ color: x.status && x.status >= 400 ? "var(--err)" : "var(--muted)", wordBreak: "break-all" }}>
                      {x.method} → {x.status ?? "…"} {x.content_type} · req {x.request}{x.response ? ` · resp ${x.response}` : ""}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </Section>

        <Section title="Connected credentials" hint="Stored encrypted. Only the label and a fingerprint are ever shown again.">
          <form onSubmit={(e) => { e.preventDefault(); void addCredential() }} style={{ display: "grid", gap: 8, gridTemplateColumns: "1fr 1fr" }}>
            <select className="h-input" value={provider} onChange={(e) => setProvider(e.target.value)} aria-label="Provider">
              {providers.filter((p) => !p.name.startsWith("http:")).map((p) => (
                <option key={p.name} value={p.name}>{p.name} — {p.description}</option>
              ))}
              <option value="__custom__">Custom HTTP API (bearer token)</option>
            </select>
            <input className="h-input" placeholder="Label (e.g. work PAT)" value={label} onChange={(e) => setLabel(e.target.value)} maxLength={128} />
            {provider === "__custom__" && (
              <input className="h-input" placeholder="Base URL, e.g. https://api.example.com" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} style={{ gridColumn: "1 / -1" }} required />
            )}
            <input className="h-input" type="password" autoComplete="off" placeholder="Secret / API key" value={secret} onChange={(e) => setSecret(e.target.value)} minLength={8} required style={{ gridColumn: "1 / -1" }} />
            <div style={{ gridColumn: "1 / -1", display: "flex", justifyContent: "flex-end" }}>
              <button className="h-btn-solid" type="submit" disabled={busy || unavailable || secret.length < 8}>Connect</button>
            </div>
          </form>

          {activeCredentials.length === 0 ? (
            <p className="h-muted" style={{ fontSize: 13, margin: 0 }}>Nothing connected yet.</p>
          ) : (
            <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "flex", flexDirection: "column", gap: 6 }}>
              {activeCredentials.map((c) => (
                <li key={c.id} style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 13 }}>
                  <span className="h-chip" style={{ cursor: "default" }}>{c.provider}</span>
                  <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis" }}>{c.label || "(no label)"}</span>
                  <span className="h-muted" style={{ ...mono, fontSize: 11 }}>{c.fingerprint}</span>
                  <button className="h-btn-ghost" onClick={() => run(() => api(`credentials/${c.id}`, { method: "DELETE" }))} disabled={busy}>Revoke</button>
                </li>
              ))}
            </ul>
          )}
          {providers.some((p) => p.system_credential) && (
            <p className="h-muted" style={{ fontSize: 12, margin: 0 }}>
              Operator-provided: {providers.filter((p) => p.system_credential).map((p) => p.name).join(", ")}
              {providers.some((p) => p.system_credential && p.name === "tavily") ? " (tavily is usable by the agent for web search without consent)" : ""}.
            </p>
          )}
        </Section>

        <Section title="Consents" hint="What the agent may use on your behalf, and for how long. Writes always pause for your approval in the chat.">
          <form onSubmit={(e) => { e.preventDefault(); void grantConsent() }} style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
            <select className="h-input" style={{ width: "auto", flex: 1, minWidth: 140 }} value={chosenConsentProvider} onChange={(e) => setConsentProvider(e.target.value)} aria-label="Provider to allow">
              {consentable.length === 0 && <option value="">Connect a credential first</option>}
              {consentable.map((p) => <option key={p} value={p}>{p}</option>)}
            </select>
            <label className="h-muted" style={{ fontSize: 12, display: "flex", alignItems: "center", gap: 6 }}>
              for <input className="h-input" type="number" min={1} max={720} value={ttlHours} onChange={(e) => setTtlHours(Number(e.target.value))} style={{ width: 70 }} /> h
            </label>
            <label className="h-muted" style={{ fontSize: 12, display: "flex", alignItems: "center", gap: 6 }}>
              <input type="checkbox" checked={allowWrite} onChange={(e) => setAllowWrite(e.target.checked)} /> allow writes (each one still asks)
            </label>
            <button className="h-btn-solid" type="submit" disabled={busy || unavailable || !chosenConsentProvider}>Allow</button>
          </form>

          {activeConsents.length === 0 ? (
            <p className="h-muted" style={{ fontSize: 13, margin: 0 }}>The agent currently has no standing access.</p>
          ) : (
            <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "flex", flexDirection: "column", gap: 6 }}>
              {activeConsents.map((c) => (
                <li key={c.id} style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 13 }}>
                  <span className="h-chip" style={{ cursor: "default" }}>{c.provider}</span>
                  <span>{c.allow_write ? "read + write" : "read-only"}</span>
                  <span className="h-muted" style={{ fontSize: 12, flex: 1 }}>until {when(c.expires_at)}</span>
                  <button className="h-btn-ghost" onClick={() => run(() => api(`consents/${c.id}`, { method: "DELETE" }))} disabled={busy}>Revoke</button>
                </li>
              ))}
            </ul>
          )}
        </Section>

        <Section title="Recent vault calls" hint="Every proxied request, without bodies or headers.">
          {audit.length === 0 ? (
            <p className="h-muted" style={{ fontSize: 13, margin: 0 }}>No calls yet.</p>
          ) : (
            <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "flex", flexDirection: "column", gap: 4, ...mono, fontSize: 12 }}>
              {audit.map((a, i) => (
                <li key={i} style={{ display: "flex", gap: 10, alignItems: "baseline" }}>
                  <span className="h-muted" style={{ width: 150, flexShrink: 0 }}>{new Date(a.ts * 1000).toLocaleString()}</span>
                  <span style={{ width: 70, flexShrink: 0 }}>{a.provider}</span>
                  <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis" }}>{a.method} {a.path}</span>
                  <span style={{ color: a.status >= 400 ? "var(--err)" : "var(--fg)" }}>{a.status}</span>
                  <span className="h-muted">{a.ms}ms</span>
                  {a.denied && <span style={{ color: "var(--err)" }}>{a.denied}</span>}
                </li>
              ))}
            </ul>
          )}
        </Section>
      </div>
    </main>
  )
}
