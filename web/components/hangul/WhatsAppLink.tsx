"use client"

import { useCallback, useEffect, useRef, useState } from "react"

/**
 * Settings → WhatsApp. Linking needs no template or SMS: the app shows a code,
 * the user sends "HANGUL <code>" to Hangul's WhatsApp number (one tap with the
 * wa.me link), and the number it comes from is linked. This polls until then.
 * Hidden entirely while the server has no WhatsApp set up.
 */
type Status = { enabled: boolean; linked: boolean; phone?: string | null; business_number?: string | null; chat_link?: string | null }
type Code = { code: string; message: string; expires_in: number; business_number?: string | null; wa_link?: string | null }

/** ``frame`` wraps the content (the page's section card), so nothing at all shows while WhatsApp is off. */
export function WhatsAppLink({ frame }: { frame: (content: React.ReactNode) => React.ReactNode }) {
  const [status, setStatus] = useState<Status | null>(null)
  const [code, setCode] = useState<Code | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const poll = useRef<ReturnType<typeof setInterval> | null>(null)

  const load = useCallback(async () => {
    const res = await fetch("/api/whatsapp/link", { cache: "no-store" }).catch(() => null)
    const s: Status | null = res && res.ok ? await res.json() : null
    setStatus(s)
    return s
  }, [])

  const stopPolling = () => { if (poll.current) clearInterval(poll.current); poll.current = null }
  // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch on mount; state is set after the await
  useEffect(() => { void load(); return stopPolling }, [load])

  const start = async () => {
    setBusy(true); setError(null)
    const res = await fetch("/api/whatsapp/link", { method: "POST" }).catch(() => null)
    setBusy(false)
    if (!res || !res.ok) { setError("Couldn't start linking. Try again in a moment."); return }
    const c: Code = await res.json()
    setCode(c)
    stopPolling()
    const until = Date.now() + c.expires_in * 1000
    poll.current = setInterval(async () => {
      const s = await load()
      if (s?.linked) { stopPolling(); setCode(null) }
      else if (Date.now() > until) { stopPolling(); setCode(null); setError("The code expired. Get a new one.") }
    }, 3000)
  }

  const unlink = async () => {
    setBusy(true)
    await fetch("/api/whatsapp/link", { method: "DELETE" }).catch(() => null)
    setBusy(false)
    void load()
  }

  if (!status?.enabled) return null
  return frame(
    <div style={{ display: "flex", flexDirection: "column", gap: 10, fontSize: 13 }} data-testid="whatsapp-link">
      {status.linked ? (
        <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <i className="ti ti-brand-whatsapp" style={{ fontSize: 18 }} />
          <span style={{ flex: 1 }} data-testid="whatsapp-linked">Linked to <b style={{ fontWeight: 500 }}>{status.phone}</b>. Message Hangul any time; reminders arrive there too.</span>
          {status.chat_link && <a href={status.chat_link} target="_blank" rel="noreferrer" className="h-btn-ghost" style={{ fontSize: 12, textDecoration: "none" }}>Open chat</a>}
          <button className="h-btn-ghost" style={{ fontSize: 12 }} onClick={() => void unlink()} disabled={busy} data-testid="whatsapp-unlink">Unlink</button>
        </div>
      ) : code ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }} data-testid="whatsapp-code">
          <span>Send this message to Hangul on WhatsApp{code.business_number ? <> (<b style={{ fontWeight: 500 }}>{code.business_number}</b>)</> : null}:</span>
          <code style={{ fontSize: 20, letterSpacing: 2, padding: "6px 10px", borderRadius: 8, background: "var(--surface-hover)", alignSelf: "flex-start" }}>
            {code.message}
          </code>
          <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            {code.wa_link && (
              <a href={code.wa_link} target="_blank" rel="noreferrer" className="h-btn-solid" style={{ textDecoration: "none", fontSize: 13 }} data-testid="whatsapp-open">
                <i className="ti ti-brand-whatsapp" style={{ marginRight: 6 }} />Open WhatsApp
              </a>
            )}
            <span className="h-muted" style={{ fontSize: 12 }}>Waiting for your message… The code works for {Math.round(code.expires_in / 60)} minutes.</span>
          </div>
        </div>
      ) : (
        <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <span className="h-muted" style={{ flex: 1 }}>Log sales, add customers and set reminders on WhatsApp, free. Plus and Pro add everything else, and your brief there.</span>
          <button className="h-btn-solid" onClick={() => void start()} disabled={busy} data-testid="whatsapp-start">
            <i className="ti ti-brand-whatsapp" style={{ marginRight: 6 }} />Link WhatsApp
          </button>
        </div>
      )}
      {error && <span style={{ color: "var(--err)", fontSize: 12 }} role="alert">{error}</span>}
    </div>
  )
}
