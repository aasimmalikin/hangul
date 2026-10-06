"use client"

import Link from "next/link"
import { useEffect, useState } from "react"
import { HangulSigil } from "@/components/HangulSigil"

/**
 * The approve-by-link card: what the scheduled task wants to do, in the words the
 * backend's approval_card uses, with Approve / Reject. Opening the page changes
 * nothing (mail scanners open links); only a button press decides.
 */

type Card = { title: string; rows: [string, string][]; body: string }
type Shown = { state: "waiting" | "expired" | "decided"; asked: string; card: Card | null; conversation_id: string | null }
type Result = { state: "approved" | "rejected" | "expired" | "decided"; answer: string; waiting_again?: boolean; conversation_id?: string | null }

export function ApproveByLink({ token, chosen }: { token: string; chosen: "approve" | "reject" | null }) {
  const [shown, setShown] = useState<Shown | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<"approve" | "reject" | null>(null)
  const [result, setResult] = useState<Result | null>(null)

  useEffect(() => {
    let live = true
    fetch(`/api/approval-links/${encodeURIComponent(token)}`, { cache: "no-store" })
      .then(async (r) => {
        const body = await r.json().catch(() => ({}))
        if (!live) return
        if (r.ok) setShown(body as Shown)
        else setError(typeof body.detail === "string" ? body.detail : "This link has expired or isn't valid.")
      })
      .catch(() => live && setError("Couldn't reach Hangul. Check your connection and reload."))
    return () => { live = false }
  }, [token])

  const decide = async (decision: "approve" | "reject") => {
    setBusy(decision); setError(null)
    try {
      const r = await fetch(`/api/approval-links/${encodeURIComponent(token)}`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ decision }),
      })
      const body = await r.json().catch(() => ({}))
      if (!r.ok) throw new Error(typeof body.detail === "string" ? body.detail : `Something went wrong (${r.status}).`)
      setResult(body as Result)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  const chat = result?.conversation_id ?? shown?.conversation_id
  return (
    <main style={{ minHeight: "100vh", display: "flex", justifyContent: "center", padding: "40px 16px", boxSizing: "border-box", background: "var(--bg)" }}>
      <div style={{ width: "100%", maxWidth: 520, display: "flex", flexDirection: "column", gap: 16 }} data-testid="approve-link">
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <HangulSigil size={28} />
          <span className="h-muted" style={{ fontSize: 13 }}>A scheduled task needs your OK</span>
        </div>

        {!shown && !error && <div className="h-surface h-shimmer" style={{ height: 180, borderRadius: 14 }} aria-busy="true" />}

        {error && !result && (
          <section className="h-surface" style={{ padding: 18, borderRadius: 14 }} role="alert" data-testid="approve-error">
            <h1 className="h-display" style={{ fontSize: 22, margin: "0 0 6px" }}>This link can&apos;t be used</h1>
            <p className="h-muted" style={{ margin: 0 }}>{error}</p>
            <p style={{ margin: "12px 0 0" }}><Link href="/kept">Open Kept in Hangul →</Link></p>
          </section>
        )}

        {shown && !result && shown.state !== "waiting" && (
          <section className="h-surface" style={{ padding: 18, borderRadius: 14 }} data-testid="approve-closed">
            <h1 className="h-display" style={{ fontSize: 22, margin: "0 0 6px" }}>
              {shown.state === "expired" ? "This has expired" : "Already decided"}
            </h1>
            <p className="h-muted" style={{ margin: 0 }}>
              {shown.state === "expired"
                ? "It waited too long, or the task ran again, so nothing will happen. The next run will ask afresh."
                : "This action was already approved or rejected — here, in the app or on WhatsApp."}
            </p>
            {chat && <p style={{ margin: "12px 0 0" }}><Link href={`/chat?c=${chat}`}>Open the chat →</Link></p>}
          </section>
        )}

        {shown?.state === "waiting" && shown.card && !result && (
          <section className="h-surface" style={{ padding: 18, borderRadius: 14, display: "flex", flexDirection: "column", gap: 12 }}>
            {shown.asked && <p className="h-muted" style={{ margin: 0, fontSize: 13 }}>From your task: “{shown.asked}”</p>}
            <h1 className="h-display" style={{ fontSize: 22, margin: 0 }} data-testid="approve-title">{shown.card.title}</h1>
            <dl style={{ margin: 0, display: "grid", gridTemplateColumns: "auto 1fr", gap: "6px 14px", fontSize: 15 }}>
              {shown.card.rows.map(([k, v]) => (
                <div key={k} style={{ display: "contents" }}>
                  <dt className="h-muted">{k}</dt>
                  <dd style={{ margin: 0, overflowWrap: "anywhere" }}>{v}</dd>
                </div>
              ))}
            </dl>
            {shown.card.body && (
              <div style={{ whiteSpace: "pre-wrap", borderLeft: "3px solid var(--surface-border)", padding: "4px 12px", fontSize: 14, maxHeight: 280, overflow: "auto" }}>
                {shown.card.body}
              </div>
            )}
            {chosen && <p className="h-muted" style={{ margin: 0, fontSize: 13 }}>Tap <b>{chosen === "approve" ? "Approve" : "Reject"}</b> to confirm.</p>}
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
              <button className="h-btn-solid" style={{ flex: "1 1 140px", padding: "12px 16px", fontSize: 16 }} disabled={busy !== null}
                autoFocus={chosen === "approve"} onClick={() => void decide("approve")} data-testid="approve-yes">
                {busy === "approve" ? "Approving…" : "Approve"}
              </button>
              <button className="h-btn-ghost" style={{ flex: "1 1 140px", padding: "12px 16px", fontSize: 16 }} disabled={busy !== null}
                autoFocus={chosen === "reject"} onClick={() => void decide("reject")} data-testid="approve-no">
                {busy === "reject" ? "Rejecting…" : "Reject"}
              </button>
            </div>
            {error && <p role="alert" style={{ margin: 0, color: "var(--err)", fontSize: 13 }}>{error}</p>}
            <p className="h-muted" style={{ margin: 0, fontSize: 12 }}>Nothing happens until you tap. This link works once and expires in 24 hours.</p>
          </section>
        )}

        {result && (
          <section className="h-surface" style={{ padding: 18, borderRadius: 14 }} data-testid="approve-done">
            <h1 className="h-display" style={{ fontSize: 22, margin: "0 0 6px" }}>
              {result.state === "approved" ? "Done ✓" : result.state === "rejected" ? "Rejected — nothing was done"
                : result.state === "expired" ? "This has expired" : "Already decided"}
            </h1>
            {result.answer && <p style={{ margin: "0 0 8px", whiteSpace: "pre-wrap" }}>{result.answer}</p>}
            {result.waiting_again && <p className="h-muted" style={{ margin: "0 0 8px" }}>It needs one more OK — open the chat to see it.</p>}
            {chat && <p style={{ margin: 0 }}><Link href={`/chat?c=${chat}`}>Open the chat →</Link></p>}
            <p className="h-muted" style={{ margin: "8px 0 0", fontSize: 12 }}>You can close this page.</p>
          </section>
        )}
      </div>
    </main>
  )
}
