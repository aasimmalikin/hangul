"use client"

import { useState } from "react"

/**
 * /vault → Work apps: connect GitHub, Notion or Slack by pasting a token.
 * The token goes straight to the backend vault (encrypted, checked with the
 * service before it is kept) and is never shown again or given to the model.
 */

type AppKey = "github" | "notion" | "slack"

const APPS: Record<AppKey, { label: string; icon: string; steps: string[]; link: string; linkText: string; placeholder: string }> = {
  github: {
    label: "GitHub", icon: "brand-github", placeholder: "github_pat_…",
    link: "https://github.com/settings/personal-access-tokens/new", linkText: "Create a fine-grained token",
    steps: ["Choose the repositories Hangul may see.", "Permissions: Issues and Pull requests → Read and write (Read only if you just want to look).", "Generate, copy, paste below."],
  },
  notion: {
    label: "Notion", icon: "brand-notion", placeholder: "ntn_…",
    link: "https://www.notion.so/profile/integrations", linkText: "Create an internal integration",
    steps: ["New integration → type Internal → copy the secret.", "In Notion, open each page Hangul may use → ••• → Connections → add your integration.", "Paste the secret below."],
  },
  slack: {
    label: "Slack", icon: "brand-slack", placeholder: "xoxp-…",
    link: "https://api.slack.com/apps", linkText: "Create a Slack app",
    steps: ["Create an app → OAuth & Permissions → User Token Scopes: search:read, channels:read, channels:history, groups:read, groups:history, chat:write.", "Install to your workspace and copy the User OAuth Token (xoxp-…).", "Paste it below."],
  },
}

export function WorkApps({ status, onChange }: { status: Partial<Record<AppKey, boolean>> | undefined; onChange: () => void }) {
  const [open, setOpen] = useState<AppKey | null>(null)
  const [token, setToken] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const call = async (app: AppKey, method: "POST" | "DELETE") => {
    setBusy(true); setError(null)
    try {
      const res = await fetch(`/api/integrations/apps/${app}`, {
        method, headers: { "Content-Type": "application/json" },
        body: method === "POST" ? JSON.stringify({ token: token.trim() }) : undefined,
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : `Request failed (${res.status})`)
      setToken(""); setOpen(null); onChange()
    } catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }} data-testid="work-apps">
      {(Object.keys(APPS) as AppKey[]).map((key) => {
        const a = APPS[key]
        const connected = Boolean(status?.[key])
        return (
          <div key={key} style={{ display: "flex", flexDirection: "column", gap: 8 }} data-testid={`app-${key}`}>
            <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
              <i className={`ti ti-${a.icon}`} style={{ fontSize: 22 }} />
              <div style={{ flex: 1, minWidth: 160, fontSize: 13 }}>
                <b>{a.label}</b> <span className="h-muted">· {connected ? "Connected" : "Not connected"}</span>
              </div>
              {connected ? (
                <button className="h-btn-ghost" disabled={busy} onClick={() => void call(key, "DELETE")} data-testid={`app-${key}-disconnect`}>Disconnect</button>
              ) : (
                <button className="h-btn-solid" onClick={() => { setOpen(open === key ? null : key); setToken(""); setError(null) }} data-testid={`app-${key}-connect`}>
                  {open === key ? "Cancel" : "Connect"}
                </button>
              )}
            </div>
            {open === key && !connected && (
              <form className="h-surface" style={{ padding: 12, display: "flex", flexDirection: "column", gap: 8 }}
                onSubmit={(e) => { e.preventDefault(); if (token.trim()) void call(key, "POST") }}>
                <ol style={{ margin: 0, paddingLeft: 18, fontSize: 12, display: "flex", flexDirection: "column", gap: 3 }} className="h-muted">
                  <li><a href={a.link} target="_blank" rel="noopener noreferrer" style={{ color: "var(--link)" }}>{a.linkText} ↗</a></li>
                  {a.steps.map((s) => <li key={s}>{s}</li>)}
                </ol>
                <div style={{ display: "flex", gap: 8 }}>
                  <input className="h-input" type="password" autoComplete="off" spellCheck={false} placeholder={a.placeholder}
                    value={token} onChange={(e) => setToken(e.target.value)} aria-label={`${a.label} token`} style={{ flex: 1 }} />
                  <button className="h-btn-solid" type="submit" disabled={busy || token.trim().length < 8}>{busy ? "Checking…" : "Save"}</button>
                </div>
                {error && <span style={{ fontSize: 12, color: "var(--err)" }} role="alert">{error}</span>}
              </form>
            )}
          </div>
        )
      })}
    </div>
  )
}
