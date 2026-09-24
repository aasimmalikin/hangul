"use client"

import { useEffect, useRef, useState } from "react"
import { useSession } from "next-auth/react"
import { loadAvailableConnectors, loadIntegrations, type ConnectorInfo, type Integrations } from "@/lib/connectors"
import Link from "next/link"

/** A document the backend indexed for this user. */
export type Attachment = {
  name: string
  chunks: number
  /** From the backend's ingest scan: passages that read like instructions to the assistant. */
  warning?: string | null
}

const ACCEPT = ".pdf,.txt,.md"

/**
 * The `+` at the left of every composer. Opens a small menu of things to add
 * (just "Docs" for now); picking one opens the file chooser and the file is
 * sent to `/api/upload`, which indexes it for the signed-in user so
 * `search_docs` can find it on the next question.
 *
 * Signed-out users never reach the file chooser: `onRequireSignIn` fires with
 * the reason to show in the page's SignInModal.
 */
export function AttachMenu({
  onUploaded,
  onUploadingChange,
  onError,
  onRequireSignIn,
  placement = "above",
  connectors = [],
  onConnectorsChange,
}: {
  /** Where the menu opens relative to the button. */
  placement?: "above" | "below"
  onUploaded: (a: Attachment) => void
  onUploadingChange?: (name: string | null) => void
  onError?: (message: string | null) => void
  onRequireSignIn: (reason: string) => void
  /** Connector keys currently on for this conversation ("+ → Connectors"). */
  connectors?: string[]
  onConnectorsChange?: (keys: string[]) => void
}) {
  const { status } = useSession()
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [sub, setSub] = useState(false)          // the Connectors submenu
  const [available, setAvailable] = useState<ConnectorInfo[] | null>(null)
  const [integrations, setIntegrations] = useState<Integrations | null>(null)
  const ref = useRef<HTMLDivElement>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  // The catalogue is fetched the first time the menu opens, not on page load.
  useEffect(() => {
    if (!open || available !== null) return
    let cancelled = false
    void loadAvailableConnectors().then((list) => { if (!cancelled) setAvailable(list) })
    return () => { cancelled = true }
  }, [open, available])

  // Per-user connectors need the user's integration status; fetched once the
  // session is known and the menu is open (the session may still be loading
  // when the menu first opens, so this is keyed on both).
  useEffect(() => {
    if (!open || status !== "authenticated" || integrations !== null) return
    let cancelled = false
    void loadIntegrations().then((i) => { if (!cancelled) setIntegrations(i ?? { google: { connected: false, products: [], scopes: [] } }) })
    return () => { cancelled = true }
  }, [open, status, integrations])

  // true/false once known; null while the integrations status is still loading
  const connectedFor = (c: ConnectorInfo): boolean | null => {
    if (!c.per_user) return true
    if (status !== "authenticated") return false
    if (integrations === null) return null
    return c.auth === "google" ? Boolean(integrations.google.connected) : true
  }

  const toggleConnector = (key: string) => {
    const next = connectors.includes(key) ? connectors.filter((k) => k !== key) : [...connectors, key]
    onConnectorsChange?.(next)
  }

  useEffect(() => {
    if (!open) return
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) { setOpen(false); setSub(false) }
    }
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") { setOpen(false); setSub(false) } }
    document.addEventListener("mousedown", onDoc)
    document.addEventListener("keydown", onKey)
    return () => { document.removeEventListener("mousedown", onDoc); document.removeEventListener("keydown", onKey) }
  }, [open])

  const onPlus = () => {
    if (status !== "authenticated") {
      onRequireSignIn("Sign in to add a document and ask questions about it.")
      return
    }
    setOpen((o) => !o)
  }

  const pickDocs = () => {
    setOpen(false)
    fileRef.current?.click()
  }

  const upload = async (file: File) => {
    setBusy(true)
    onUploadingChange?.(file.name)
    onError?.(null)
    try {
      const form = new FormData()
      form.append("file", file)
      const res = await fetch("/api/upload", { method: "POST", body: form, signal: AbortSignal.timeout(120_000) })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        if (res.status === 401) {
          onRequireSignIn("Your session has expired. Sign in again to add the document.")
          return
        }
        onError?.(typeof data.detail === "string" ? data.detail : `Upload failed (${res.status})`)
        return
      }
      onUploaded({ name: data.filename ?? file.name, chunks: data.chunks_indexed ?? 0, warning: data.security?.warning ?? null })
    } catch (e) {
      onError?.((e as Error)?.name === "TimeoutError"
        ? "The upload timed out. Try a smaller file."
        : "Upload failed. Check your connection and try again.")
    } finally {
      setBusy(false)
      onUploadingChange?.(null)
      if (fileRef.current) fileRef.current.value = ""
    }
  }

  return (
    <div ref={ref} style={{ position: "relative", flexShrink: 0 }}>
      <input
        ref={fileRef}
        type="file"
        accept={ACCEPT}
        hidden
        onChange={(e) => { const f = e.target.files?.[0]; if (f) upload(f) }}
      />
      <button
        type="button"
        className="h-icon-btn"
        style={{ borderRadius: "50%" }}
        onClick={onPlus}
        disabled={busy}
        aria-label="Add"
        aria-haspopup="menu"
        aria-expanded={open}
        title="Add"
      >
        <i className={`ti ${busy ? "ti-loader-2 animate-spin" : "ti-plus"}`} style={{ fontSize: 16 }} />
      </button>

      {open && (
        <div className="h-popover" role="menu" style={{ position: "absolute", ...(placement === "above" ? { bottom: 40 } : { top: 40 }), left: 0, minWidth: 140, zIndex: 30 }}>
          <button
            role="menuitem"
            className="h-btn-ghost"
            style={{ width: "100%", justifyContent: "flex-start", padding: "8px 10px", gap: 10 }}
            onClick={pickDocs}
          >
            <i className="ti ti-file-text" style={{ fontSize: 15 }} />
            Docs
          </button>
          {onConnectorsChange && (
            <div
              style={{ position: "relative" }}
              onMouseEnter={() => setSub(true)}
              onMouseLeave={() => setSub(false)}
            >
              {/* Hover opens the submenu (like the desktop apps); click/Enter
                  toggles it for touch and keyboard users. */}
              <button
                role="menuitem"
                aria-haspopup="menu"
                aria-expanded={sub}
                className="h-btn-ghost"
                style={{ width: "100%", justifyContent: "flex-start", padding: "8px 10px", gap: 10 }}
                onClick={() => setSub(true)}
                data-testid="menu-connectors"
              >
                <i className="ti ti-plug" style={{ fontSize: 15 }} />
                Connectors
                {connectors.length > 0 && <span className="h-muted" style={{ fontSize: 11 }}>{connectors.length} on</span>}
                <i className="ti ti-chevron-right" style={{ fontSize: 13, marginLeft: "auto" }} />
              </button>
              {sub && (
                <div
                  className="h-popover"
                  role="menu"
                  aria-label="Connectors"
                  style={{ position: "absolute", left: "100%", top: -8, marginLeft: 4, minWidth: 220, zIndex: 31 }}
                  data-testid="connectors-menu"
                >
                  {available === null && <div className="h-muted" style={{ padding: "8px 10px", fontSize: 12 }}>Loading…</div>}
                  {available !== null && available.length === 0 && (
                    <div className="h-muted" style={{ padding: "8px 10px", fontSize: 12 }}>No connectors available.</div>
                  )}
                  {(available ?? []).map((c) => {
                    const on = connectors.includes(c.key)
                    const state = connectedFor(c)
                    if (state === null) {
                      return (
                        <div key={c.key} className="h-muted" style={{ padding: "8px 10px", fontSize: 12, display: "flex", gap: 10 }} data-testid={`connector-${c.key}-checking`}>
                          <i className={`ti ti-${c.icon}`} style={{ fontSize: 15 }} /> {c.label} · checking…
                        </div>
                      )
                    }
                    if (!state) {
                      return (
                        <Link key={c.key} href="/vault" role="menuitem" className="h-btn-ghost" data-testid={`connector-${c.key}`}
                          style={{ width: "100%", justifyContent: "flex-start", padding: "8px 10px", gap: 10, alignItems: "flex-start", textDecoration: "none" }}
                          onClick={() => { setOpen(false); setSub(false) }} title={c.description}>
                          <i className={`ti ti-${c.icon}`} style={{ fontSize: 15, marginTop: 1 }} />
                          <span style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", flex: 1 }}>
                            <span>{c.label}</span>
                            <span className="h-muted" style={{ fontSize: 11 }}>Connect your account first →</span>
                          </span>
                        </Link>
                      )
                    }
                    return (
                      <button
                        key={c.key}
                        role="menuitemcheckbox"
                        aria-checked={on}
                        className="h-btn-ghost"
                        style={{ width: "100%", justifyContent: "flex-start", padding: "8px 10px", gap: 10, alignItems: "flex-start" }}
                        onClick={() => toggleConnector(c.key)}
                        data-testid={`connector-${c.key}`}
                        title={c.description}
                      >
                        <i className={`ti ti-${c.icon}`} style={{ fontSize: 15, marginTop: 1 }} />
                        <span style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", flex: 1 }}>
                          <span>{c.label}</span>
                          <span className="h-muted" style={{ fontSize: 11 }}>{c.description}</span>
                        </span>
                        <i className={`ti ${on ? "ti-toggle-right" : "ti-toggle-left"}`} style={{ fontSize: 18, color: on ? "var(--fg)" : "var(--muted)" }} aria-hidden />
                      </button>
                    )
                  })}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
