"use client"

import { useEffect, useRef, useState } from "react"
import { ModelPicker } from "@/components/hangul/ModelPicker"

/**
 * The composer's single "Options" button: everything most people never need
 * to touch, kept out of the way. Inside: Only my files, Research mode, using
 * connected apps automatically, and the model / speed-vs-depth picker.
 */
export function ComposerOptions({
  docsOnly, onDocsOnly, research, onResearch, autoApps, onAutoApps, model, effort, onModel, disabled,
}: {
  docsOnly: boolean; onDocsOnly: (v: boolean) => void
  research: boolean; onResearch: (v: boolean) => void
  autoApps: boolean; onAutoApps: (v: boolean) => void
  model: string | null; effort: string | null; onModel: (m: string | null, e: string | null) => void
  disabled?: boolean
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const onDoc = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false) }
    document.addEventListener("mousedown", onDoc)
    return () => document.removeEventListener("mousedown", onDoc)
  }, [open])

  const row = (testId: string, icon: string, label: string, hint: string, on: boolean, set: (v: boolean) => void) => (
    <label data-testid={testId} style={{ display: "flex", gap: 10, alignItems: "flex-start", padding: "8px 10px", borderRadius: 8, cursor: "pointer" }}>
      <i className={`ti ti-${icon}`} style={{ fontSize: 16, marginTop: 1 }} />
      <span style={{ flex: 1 }}>
        <span style={{ fontSize: 13, display: "block" }}>{label}</span>
        <span className="h-muted" style={{ fontSize: 11 }}>{hint}</span>
      </span>
      <input type="checkbox" checked={on} onChange={(e) => set(e.target.checked)} aria-label={label}
        style={{ width: 16, height: 16, accentColor: "var(--fg)", marginTop: 2 }} />
    </label>
  )

  return (
    <div ref={ref} style={{ position: "relative" }}>
      <button type="button" className="h-chip" data-testid="composer-options" aria-haspopup="dialog" aria-expanded={open}
        onClick={() => setOpen((o) => !o)} style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
        <i className="ti ti-adjustments-horizontal" style={{ fontSize: 12 }} /> Options
      </button>
      {open && (
        <div className="h-popover" role="dialog" aria-label="Options"
          style={{ position: "absolute", bottom: 36, left: 0, width: 300, zIndex: 40, padding: 6, display: "flex", flexDirection: "column" }}>
          {row("opt-docs-only", "book-2", "Only my files", "Answer only from documents you uploaded — no web", docsOnly, onDocsOnly)}
          {row("opt-research", "telescope", "Research mode", "Several searches, cited sources; slower and deeper", research, onResearch)}
          {row("opt-auto-apps", "plug-connected", "Use my apps automatically", "Turn on Gmail, Calendar… when a message needs them", autoApps, onAutoApps)}
          <div style={{ borderTop: "0.5px solid var(--surface-border)", margin: "4px 0", paddingTop: 8 }}>
            <div className="h-muted" style={{ fontSize: 11, padding: "0 10px 6px" }}>Model and speed vs. depth</div>
            <div style={{ padding: "0 8px 4px" }}>
              <ModelPicker model={model} effort={effort} disabled={disabled} onChange={onModel} />
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
