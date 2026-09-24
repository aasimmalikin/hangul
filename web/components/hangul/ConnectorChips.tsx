"use client"

import { useEffect, useState } from "react"
import { loadAvailableConnectors, type ConnectorInfo } from "@/lib/connectors"

/** One chip per connector that is on; clicking a chip switches it off. */
export function ConnectorChips({ keys, onChange }: { keys: string[]; onChange: (next: string[]) => void }) {
  const [info, setInfo] = useState<ConnectorInfo[] | null>(null)
  useEffect(() => {
    if (keys.length === 0 || info !== null) return
    let cancelled = false
    void loadAvailableConnectors().then((list) => { if (!cancelled) setInfo(list) })
    return () => { cancelled = true }
  }, [keys.length, info])
  if (keys.length === 0) return null
  return (
    <>
      {keys.map((k) => {
        const c = info?.find((x) => x.key === k)
        return (
          <button
            key={k}
            type="button"
            className="h-chip"
            aria-pressed
            onClick={() => onChange(keys.filter((x) => x !== k))}
            title={`${c?.description ?? k} — click to switch off`}
            data-testid={`chip-connector-${k}`}
            style={{ background: "var(--solid-bg)", color: "var(--solid-fg)", borderColor: "var(--solid-bg)" }}
          >
            <i className={`ti ti-${c?.icon ?? "plug"}`} style={{ fontSize: 12, marginRight: 5 }} />
            {c?.label ?? k}
            <i className="ti ti-x" style={{ fontSize: 11, marginLeft: 6 }} aria-hidden />
          </button>
        )
      })}
    </>
  )
}
