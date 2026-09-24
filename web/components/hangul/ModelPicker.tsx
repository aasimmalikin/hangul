"use client"

import { useEffect, useRef, useState } from "react"

/** One row of the backend registry (`GET /models`). */
export type ModelInfo = {
  id: string
  label: string
  input_usd_per_m: number
  output_usd_per_m: number
  supports_reasoning: boolean
  efforts: string[]
  default_effort: string | null
}
type Catalog = { default: { model: string; effort: string | null }; models: ModelInfo[] }

type Props = {
  /** The tab's current choice; null = the server default. */
  model: string | null
  effort: string | null
  onChange: (model: string | null, effort: string | null) => void
  disabled?: boolean
}

const fmt = (n: number) => (n < 1 ? `$${n.toFixed(2)}` : `$${n % 1 ? n.toFixed(2) : n}`)

/**
 * Two chips beside "Documents only": which model answers and how hard it
 * thinks. The list comes from the backend registry, so prices and the
 * effort levels each model accepts are never duplicated here. Hidden until
 * the catalog has loaded, and stays hidden if it never does (the server
 * default still answers).
 */
export function ModelPicker({ model, effort, onChange, disabled }: Props) {
  const [catalog, setCatalog] = useState<Catalog | null>(null)
  const [open, setOpen] = useState<"model" | "effort" | null>(null)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    let alive = true
    fetch("/api/models", { signal: AbortSignal.timeout(10_000) })
      .then((r) => (r.ok ? r.json() : null))
      .then((c: Catalog | null) => { if (alive && c && Array.isArray(c.models)) setCatalog(c) })
      .catch(() => { /* picker just stays hidden */ })
    return () => { alive = false }
  }, [])

  useEffect(() => {
    if (!open) return
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(null)
    }
    document.addEventListener("mousedown", onDoc)
    return () => document.removeEventListener("mousedown", onDoc)
  }, [open])

  if (!catalog) return null

  const currentId = model ?? catalog.default.model
  const current = catalog.models.find((m) => m.id === currentId) ?? catalog.models[0]
  const currentEffort = current.supports_reasoning
    ? (effort && current.efforts.includes(effort) ? effort : (currentId === catalog.default.model && catalog.default.effort) || current.default_effort)
    : null

  const pickModel = (m: ModelInfo) => {
    // Keep the effort if the new model accepts it; otherwise its own default.
    const e = m.supports_reasoning ? (effort && m.efforts.includes(effort) ? effort : m.default_effort) : null
    onChange(m.id, e)
    setOpen(null)
  }
  const pickEffort = (e: string) => { onChange(current.id, e); setOpen(null) }

  const chip = (which: "model" | "effort", testId: string, icon: string, text: string, title: string) => (
    <button
      type="button"
      className="h-chip"
      data-testid={testId}
      disabled={disabled}
      aria-haspopup="listbox"
      aria-expanded={open === which}
      onClick={() => setOpen((o) => (o === which ? null : which))}
      title={title}
      style={{ display: "inline-flex", alignItems: "center", gap: 5 }}
    >
      <i className={`ti ti-${icon}`} style={{ fontSize: 12 }} />
      {text}
      <i className="ti ti-chevron-down" style={{ fontSize: 11, color: "var(--muted)" }} />
    </button>
  )

  const option = (key: string, selected: boolean, onPick: () => void, main: string, hint?: string, testId?: string) => (
    <button
      key={key}
      type="button"
      role="option"
      aria-selected={selected}
      data-testid={testId}
      onClick={onPick}
      style={{
        display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16,
        width: "100%", padding: "7px 10px", borderRadius: 8, border: 0, cursor: "pointer",
        background: selected ? "var(--surface-hover)" : "transparent", color: "var(--fg)",
        fontSize: 13, textAlign: "left",
      }}
      onMouseEnter={(e) => { e.currentTarget.style.background = "var(--surface-hover)" }}
      onMouseLeave={(e) => { e.currentTarget.style.background = selected ? "var(--surface-hover)" : "transparent" }}
    >
      <span>{main}</span>
      {hint && <span style={{ fontSize: 11, color: "var(--muted)", whiteSpace: "nowrap" }}>{hint}</span>}
    </button>
  )

  return (
    <div ref={ref} style={{ position: "relative", display: "inline-flex", gap: 6 }}>
      {chip("model", "model-picker", "cpu", current.label,
        `${fmt(current.input_usd_per_m)} in / ${fmt(current.output_usd_per_m)} out per 1M tokens`)}
      {current.supports_reasoning && currentEffort &&
        chip("effort", "effort-picker", "brain", `Effort: ${currentEffort}`,
          "How hard the model thinks — higher means slower, more thorough, and more steps")}

      {open && (
        <div
          className="h-popover"
          role="listbox"
          style={{ position: "absolute", bottom: 36, left: 0, minWidth: open === "model" ? 280 : 180, zIndex: 30 }}
        >
          {open === "model"
            ? catalog.models.map((m) =>
                option(m.id, m.id === current.id, () => pickModel(m), m.label,
                  `${fmt(m.input_usd_per_m)} / ${fmt(m.output_usd_per_m)}`, `model-option-${m.id}`))
            : current.efforts.map((e) =>
                option(e, e === currentEffort, () => pickEffort(e), e, undefined, `effort-option-${e}`))}
          {open === "model" && (
            <div style={{ fontSize: 11, color: "var(--muted)", padding: "6px 10px 2px" }}>
              Price per 1M tokens: input / output
            </div>
          )}
        </div>
      )}
    </div>
  )
}
