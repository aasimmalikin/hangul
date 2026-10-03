"use client"

import { useState } from "react"

/**
 * "Before you go": what happens when someone taps Cancel plan.
 *   1. Why? (one tap)
 *   2. One alternative that fits that reason -- and, always, Keep my plan
 *      and Cancel anyway side by side. Cancelling stays one click: no
 *      guilt-tripping, no extra screens (subscription traps are illegal and
 *      just turn into chargebacks).
 * The reason and the outcome are saved (POST /api/billing/leave), so the
 * admin page shows why people leave and how many stay.
 */

type Reason = "too_expensive" | "not_using" | "missing_feature" | "not_working" | "switching" | "other"

const REASONS: Array<{ key: Reason; label: string; icon: string }> = [
  { key: "too_expensive", label: "It's too expensive", icon: "currency-rupee" },
  { key: "not_using", label: "I'm not using it enough", icon: "clock-pause" },
  { key: "missing_feature", label: "It's missing something I need", icon: "puzzle" },
  { key: "not_working", label: "Something isn't working", icon: "bug" },
  { key: "switching", label: "I'm switching to another app", icon: "arrows-exchange" },
  { key: "other", label: "Something else", icon: "dots" },
]

export function CancelFlow({ plan, planLabel, endsAt, onClose, onDone }: {
  plan: string
  planLabel: string
  /** when the paid period ends (shown so nobody fears losing what they paid for) */
  endsAt: string | null
  onClose: () => void
  onDone: (message: string) => void
}) {
  const [reason, setReason] = useState<Reason | null>(null)
  const [detail, setDetail] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const until = endsAt ? new Date(endsAt).toLocaleDateString(undefined, { day: "numeric", month: "long" }) : "the end of this billing period"

  const act = async (action: "keep" | "downgrade" | "cancel") => {
    if (!reason) return
    setBusy(true); setError(null)
    try {
      const res = await fetch("/api/billing/leave", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reason, detail: detail.trim(), action }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : `Request failed (${res.status})`)
      onDone(action === "keep" ? `Great — you're still on ${planLabel}.`
        : action === "downgrade" ? "Done — you're on Plus now. The unused part of Pro is credited."
        : `Your plan is cancelled. You keep ${planLabel} until ${until}, then move to Free — your chats, files and credits stay.`)
    } catch (e) { setError((e as Error).message); setBusy(false) }
  }

  // one alternative that fits the reason (null = just the two buttons)
  const offer = (() => {
    if (!reason) return null
    if (reason === "too_expensive" && plan === "pro") {
      return { icon: "arrow-down-circle", title: "Switch to Plus instead", body: "Most of what you use, for a fifth of the price. The unused part of Pro is credited.",
               cta: "Switch to Plus", action: "downgrade" as const }
    }
    if (reason === "too_expensive" || reason === "not_using") {
      return { icon: "shield-check", title: "Nothing is lost on Free", body: `If you cancel you keep ${planLabel} until ${until}. After that your chats, files, lists and credits all stay — and you can buy credits only when you need them.`, cta: null, action: null }
    }
    if (reason === "missing_feature" || reason === "not_working") {
      return { icon: "message-circle", title: reason === "missing_feature" ? "What's missing?" : "What went wrong?", body: "Tell us — we read every message, and it may already be on the way.", cta: null, action: null, ask: true }
    }
    return { icon: "message-circle", title: "Anything we could do better?", body: "Optional, but it really helps.", cta: null, action: null, ask: true }
  })()

  return (
    <div role="dialog" aria-modal="true" aria-label="Cancel plan" data-testid="cancel-flow"
      style={{ position: "fixed", inset: 0, zIndex: 70, background: "var(--scrim)", display: "grid", placeItems: "center", padding: 16 }}>
      <div className="h-popover" style={{ width: "100%", maxWidth: 440, padding: "20px 20px 16px", display: "flex", flexDirection: "column", gap: 12 }}>
        <div style={{ display: "flex", alignItems: "center" }}>
          <h2 className="h-display" style={{ fontSize: 20, margin: 0, flex: 1 }}>{reason ? "Before you go" : "Why are you cancelling?"}</h2>
          <button className="h-btn-ghost" aria-label="Close" onClick={onClose} style={{ padding: "2px 6px" }}><i className="ti ti-x" /></button>
        </div>

        {!reason ? (
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }} data-testid="cancel-reasons">
            {REASONS.map((r) => (
              <button key={r.key} className="h-btn-outline" onClick={() => setReason(r.key)}
                style={{ justifyContent: "flex-start", gap: 10, padding: "10px 12px" }}>
                <i className={`ti ti-${r.icon}`} style={{ fontSize: 16 }} />{r.label}
              </button>
            ))}
            <button className="h-btn-ghost" onClick={onClose} style={{ fontSize: 13 }}>Never mind, keep my plan</button>
          </div>
        ) : (
          <>
            {offer && (
              <div className="h-surface" style={{ padding: 12, display: "flex", gap: 10, alignItems: "flex-start" }} data-testid="cancel-offer">
                <i className={`ti ti-${offer.icon}`} style={{ fontSize: 20, marginTop: 1 }} />
                <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 6 }}>
                  <b style={{ fontWeight: 500, fontSize: 14 }}>{offer.title}</b>
                  <span className="h-muted" style={{ fontSize: 13 }}>{offer.body}</span>
                  {"ask" in offer && offer.ask && (
                    <textarea className="h-input" rows={3} maxLength={1000} value={detail} onChange={(e) => setDetail(e.target.value)}
                      placeholder="Optional" aria-label="Tell us more" style={{ resize: "vertical" }} />
                  )}
                  {offer.cta && offer.action && (
                    <button className="h-btn-solid" disabled={busy} onClick={() => void act(offer.action)} style={{ alignSelf: "flex-start" }}
                      data-testid="cancel-offer-cta">{offer.cta}</button>
                  )}
                </div>
              </div>
            )}
            {error && <span style={{ fontSize: 12, color: "var(--err)" }} role="alert">{error}</span>}
            <div style={{ display: "flex", gap: 8 }}>
              <button className="h-btn-solid" disabled={busy} onClick={() => void act("keep")} style={{ flex: 1 }} data-testid="cancel-keep">
                Keep my plan
              </button>
              <button className="h-btn-outline" disabled={busy} onClick={() => void act("cancel")} style={{ flex: 1 }} data-testid="cancel-confirm">
                {busy ? "…" : "Cancel anyway"}
              </button>
            </div>
            <span className="h-muted" style={{ fontSize: 11, textAlign: "center" }}>
              Cancelling keeps {planLabel} until {until}. You can undo it any time before then.
            </span>
          </>
        )}
      </div>
    </div>
  )
}
