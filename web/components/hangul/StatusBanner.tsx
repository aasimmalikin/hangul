"use client"

import type { Connectivity } from "@/components/hangul/useConnectivity"

/** One line under the header when something is wrong with the connection. */
export function StatusBanner({ c }: { c: Connectivity }) {
  if (c.online && c.backendOk !== false) return null
  const text = !c.online
    ? "You're offline. Your conversation is saved; sending will resume when you're back."
    : "The assistant is unreachable right now. Retrying automatically…"
  return (
    <div
      role="status"
      data-testid="status-banner"
      style={{
        margin: "0 18px 6px", padding: "8px 12px", borderRadius: 10, fontSize: 13,
        background: "var(--warn-bg)", border: "0.5px solid var(--warn)", color: "var(--fg)",
        display: "flex", alignItems: "center", gap: 8,
      }}
    >
      <i className={`ti ${c.online ? "ti-plug-connected-x" : "ti-wifi-off"}`} style={{ color: "var(--warn)" }} />
      <span style={{ flex: 1 }}>{text}</span>
      {c.online && (
        <button className="h-btn-ghost" style={{ padding: "4px 10px", fontSize: 12 }} onClick={() => void c.recheck()}>
          Check now
        </button>
      )}
    </div>
  )
}
