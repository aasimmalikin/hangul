"use client"

import { useEffect, useRef, useState } from "react"
import { useSession } from "next-auth/react"
import { loadAvailableConnectors, loadIntegrations, offeredTo, type ConnectorInfo, type Integrations } from "@/lib/connectors"
import Link from "next/link"
import { Recorder, voiceSupported } from "@/lib/voice"

/** A document the backend indexed for this user. */
export type Attachment = {
  name: string
  chunks: number
  /** From the backend's ingest scan: passages that read like instructions to the assistant. */
  warning?: string | null
}

const ACCEPT = ".pdf,.txt,.md,.docx,.xlsx,.csv,.png,.jpg,.jpeg,.webp,.gif,.mp3,.m4a,.wav,.webm,.ogg"

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
  const [noteSecs, setNoteSecs] = useState<number | null>(null)   // recording a voice note
  const noteRec = useRef<Recorder | null>(null)
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

  // "ok" / "connect" (no account) / "grant" (account connected, this
  // product's scopes not granted); null while integrations are still loading
  const connectedFor = (c: ConnectorInfo): "ok" | "connect" | "grant" | null => {
    if (!c.per_user) return "ok"
    if (status !== "authenticated") return "connect"
    if (integrations === null) return null
    if (c.auth?.startsWith("vault:")) return integrations.apps?.[c.auth.slice(6) as "github" | "notion" | "slack"] ? "ok" : "connect"
    if (c.auth !== "google") return "ok"
    if (!integrations.google.connected) return "connect"
    return !c.product || integrations.google.products.includes(c.product) ? "ok" : "grant"
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

  // A voice note is recorded here and uploaded like any file: the backend
  // transcribes and indexes it, so "summarise my voice note" works.
  const recordNote = async () => {
    setOpen(false)
    const r = (noteRec.current = new Recorder())
    setNoteSecs(-1)                       // -1 = waiting for the browser's mic permission
    let tick: number | undefined
    let rec
    try {
      rec = await r.start({ maxMs: 10 * 60_000, onStart: () => {
        setNoteSecs(0)
        tick = window.setInterval(() => setNoteSecs((x) => (x ?? 0) + 1), 1000)
      } })
    } catch {
      onError?.("Allow microphone access in your browser to record a voice note.")
    } finally {
      window.clearInterval(tick)
      setNoteSecs(null)
    }
    if (!rec || rec.seconds < 1) return
    const stamp = new Date().toISOString().slice(0, 16).replace(/[-:T]/g, "")
    await upload(new File([rec.blob], `voice-note-${stamp}.${rec.ext}`, { type: rec.blob.type }))
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
      {noteSecs === -1 && (
        <button type="button" className="h-btn-ghost" data-testid="voice-note-waiting"
          onClick={() => noteRec.current?.cancel()} aria-label="Cancel the voice note"
          style={{ position: "absolute", bottom: 40, left: 0, zIndex: 31, gap: 6, whiteSpace: "nowrap" }}>
          <i className="ti ti-loader-2 animate-spin" style={{ fontSize: 13 }} />
          Allow microphone access… — tap to cancel
        </button>
      )}
      {noteSecs !== null && noteSecs >= 0 && (
        <div style={{ position: "absolute", bottom: 40, left: 0, zIndex: 31, display: "flex", gap: 6 }}>
          <button type="button" className="h-btn-solid" data-testid="voice-note-stop"
            onClick={() => noteRec.current?.stop()} aria-label="Stop recording the voice note"
            style={{ gap: 6, whiteSpace: "nowrap", background: "var(--err)" }}>
            <i className="ti ti-player-stop-filled" style={{ fontSize: 13 }} />
            Recording {Math.floor(noteSecs / 60)}:{String(noteSecs % 60).padStart(2, "0")} · Stop
          </button>
          <button type="button" className="h-btn-ghost" data-testid="voice-note-cancel"
            onClick={() => noteRec.current?.cancel()} aria-label="Discard the voice note" title="Discard">
            <i className="ti ti-x" style={{ fontSize: 13 }} />
          </button>
        </div>
      )}
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
            <i className="ti ti-paperclip" style={{ fontSize: 15 }} />
            Files & photos
          </button>
          {voiceSupported() && (
            <button
              role="menuitem"
              className="h-btn-ghost"
              style={{ width: "100%", justifyContent: "flex-start", padding: "8px 10px", gap: 10 }}
              onClick={() => void recordNote()}
              data-testid="menu-voice-note"
            >
              <i className="ti ti-microphone" style={{ fontSize: 15 }} />
              Record a voice note
            </button>
          )}
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
                Apps
                {connectors.length > 0 && <span className="h-muted" style={{ fontSize: 11 }}>{connectors.length} on</span>}
                <i className="ti ti-chevron-right" style={{ fontSize: 13, marginLeft: "auto" }} />
              </button>
              {sub && (
                <div
                  className="h-popover"
                  role="menu"
                  aria-label="Apps"
                  style={{ position: "absolute", left: "100%", top: -8, marginLeft: 4, minWidth: 220, zIndex: 31 }}
                  data-testid="connectors-menu"
                >
                  {available === null && <div className="h-muted" style={{ padding: "8px 10px", fontSize: 12 }}>Loading…</div>}
                  {available !== null && available.length === 0 && (
                    <div className="h-muted" style={{ padding: "8px 10px", fontSize: 12 }}>No connectors available.</div>
                  )}
                  {/* ungrouped first, then each group under its heading (stable within each) */}
                  {[...(available ?? [])].filter((c) => offeredTo(c, integrations)).sort((a, b) => Number(Boolean(a.group)) - Number(Boolean(b.group))).map((c, i, list) => {
                    const on = connectors.includes(c.key)
                    const state = connectedFor(c)
                    // A heading above the first connector of each group (the Google products).
                    const heading = c.group && c.group !== list[i - 1]?.group
                      ? (
                        <div key={`group-${c.group}`} className="h-muted" data-testid={`connector-group-${c.group}`}
                          style={{ padding: "8px 10px 2px", fontSize: 11, display: "flex", gap: 6, alignItems: "center", borderTop: i > 0 ? "0.5px solid var(--surface-border)" : undefined, marginTop: i > 0 ? 4 : 0 }}>
                          {c.auth === "google" && <i className="ti ti-brand-google" style={{ fontSize: 12 }} aria-hidden />} {c.group}
                        </div>
                      )
                      : null
                    const item = renderConnector(c, on, state)
                    return heading ? [heading, item] : item
                  })}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )

  function renderConnector(c: ConnectorInfo, on: boolean, state: ReturnType<typeof connectedFor>) {
    // Grouped connectors sit indented under their heading.
    const padding = `8px 10px 8px ${c.group ? 18 : 10}px`
    if (state === null) {
      return (
        <div key={c.key} className="h-muted" style={{ padding, fontSize: 12, display: "flex", gap: 10 }} data-testid={`connector-${c.key}-checking`}>
          <i className={`ti ti-${c.icon}`} style={{ fontSize: 15 }} /> {c.label} · checking…
        </div>
      )
    }
    if (state !== "ok") {
      return (
        <Link key={c.key} href="/vault" role="menuitem" className="h-btn-ghost" data-testid={`connector-${c.key}`}
          style={{ width: "100%", justifyContent: "flex-start", padding, gap: 10, alignItems: "flex-start", textDecoration: "none" }}
          onClick={() => { setOpen(false); setSub(false) }} title={c.description}>
          <i className={`ti ti-${c.icon}`} style={{ fontSize: 15, marginTop: 1 }} />
          <span style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", flex: 1 }}>
            <span>{c.label}</span>
            <span className="h-muted" style={{ fontSize: 11 }}>
              {state === "grant" ? `Grant ${c.label} access →` : "Connect your account first →"}
            </span>
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
        style={{ width: "100%", justifyContent: "flex-start", padding, gap: 10, alignItems: "flex-start" }}
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
  }
}
