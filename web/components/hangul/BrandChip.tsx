"use client"

import Link from "next/link"
import { useEffect, useRef, useState } from "react"
import { type Brand, BRAND_SAVED_EVENT, Swatches } from "@/components/hangul/BrandSetup"

/**
 * "For: Chinar Café" above the message box: the brand this chat makes things
 * for. Hidden for users with no brands. `value` null = none on; picking "No
 * brand" calls onChange(null). The server also picks a brand named in a
 * message, and the page shows that here after the answer.
 */
let cache: { at: number; brands: Brand[] } | null = null

async function loadBrands(force = false): Promise<Brand[]> {
  if (!force && cache && Date.now() - cache.at < 60_000) return cache.brands
  const res = await fetch("/api/brands", { cache: "no-store" }).catch(() => null)
  const brands: Brand[] = res?.ok ? ((await res.json()).brands ?? []) : []
  cache = { at: Date.now(), brands }
  return brands
}

export function BrandChip({ value, onChange, disabled }: { value: number | null; onChange: (id: number | null) => void; disabled?: boolean }) {
  const [brands, setBrands] = useState<Brand[]>([])
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLDivElement>(null)

  useEffect(() => {
    let alive = true
    void loadBrands().then((b) => { if (alive) setBrands(b) })
    const saved = (e: Event) => {
      void loadBrands(true).then((b) => { if (alive) setBrands(b) })
      const b = (e as CustomEvent<Brand>).detail
      if (b?.id) onChange(b.id)
    }
    window.addEventListener(BRAND_SAVED_EVENT, saved)
    return () => { alive = false; window.removeEventListener(BRAND_SAVED_EVENT, saved) }
  }, [onChange])

  useEffect(() => {
    if (!open) return
    const close = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false) }
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false) }
    document.addEventListener("mousedown", close)
    document.addEventListener("keydown", esc)
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", esc) }
  }, [open])

  const usable = brands.filter((b) => !b.paused)
  const current = brands.find((b) => b.id === value)
  if (usable.length === 0 && !current) return null

  return (
    <div ref={box} style={{ position: "relative" }}>
      <button type="button" className="h-chip" data-testid="brand-chip" aria-haspopup="menu" aria-expanded={open} disabled={disabled}
        onClick={() => setOpen((o) => !o)} title={current ? `Making things for ${current.name}` : "Make things for one of your brands"}
        style={current ? { background: "var(--solid-bg)", color: "var(--solid-fg)", borderColor: "var(--solid-bg)" } : undefined}>
        <i className="ti ti-palette" style={{ fontSize: 12, marginRight: 5 }} />
        {current ? `For: ${current.name}` : "Brand"}
        <i className="ti ti-chevron-down" style={{ fontSize: 11, marginLeft: 4 }} aria-hidden />
      </button>
      {open && (
        <div role="menu" className="h-surface" data-testid="brand-menu"
          style={{ position: "absolute", bottom: "calc(100% + 6px)", left: 0, zIndex: 30, minWidth: 220, padding: 6, borderRadius: 12,
                   display: "flex", flexDirection: "column", gap: 2, boxShadow: "0 8px 24px rgba(0,0,0,0.12)" }}>
          {usable.map((b) => (
            <button key={b.id} role="menuitemradio" aria-checked={b.id === value} className="h-btn-ghost" data-testid={`brand-option-${b.id}`}
              onClick={() => { onChange(b.id); setOpen(false) }}
              style={{ justifyContent: "flex-start", gap: 8, fontSize: 13, fontWeight: b.id === value ? 600 : 400 }}>
              <Swatches colors={b.colors.slice(0, 3)} /> {b.name}
            </button>
          ))}
          <button role="menuitemradio" aria-checked={value === null} className="h-btn-ghost" data-testid="brand-off"
            onClick={() => { onChange(null); setOpen(false) }} style={{ justifyContent: "flex-start", fontSize: 13 }}>
            No brand
          </button>
          <Link href="/brands" className="h-btn-ghost" style={{ justifyContent: "flex-start", fontSize: 12, textDecoration: "none" }}>
            Open the Brand Studio →
          </Link>
        </div>
      )}
    </div>
  )
}
