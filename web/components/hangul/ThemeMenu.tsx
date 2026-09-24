"use client"

import { useEffect, useRef, useState } from "react"
import Link from "next/link"
import { useTheme } from "@/components/ThemeProvider"

/**
 * The gear button: light/dark toggle plus the way into the admin console.
 * The link is visible to everyone -- the console itself does the gating
 * (Google sign-in, backend allowlist) -- so there is nothing to discover by
 * hiding it. Shared by every page header.
 */
export function ThemeMenu() {
  const { theme, setTheme } = useTheme()
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener("mousedown", onDoc)
    return () => document.removeEventListener("mousedown", onDoc)
  }, [open])

  const swatch = (t: "light" | "dark", icon: string) => (
    <button
      key={t}
      onClick={() => { setTheme(t); setOpen(false) }}
      aria-label={`${t} theme`}
      aria-pressed={theme === t}
      style={{
        width: 34, height: 34, borderRadius: 8, cursor: "pointer",
        border: "0.5px solid var(--surface-border)",
        background: theme === t ? "var(--solid-bg)" : "transparent",
        display: "flex", alignItems: "center", justifyContent: "center",
      }}
    >
      <i className={`ti ti-${icon}`} style={{ color: theme === t ? "var(--solid-fg)" : "var(--fg)", fontSize: 16 }} />
    </button>
  )

  return (
    <div ref={ref} style={{ position: "relative" }}>
      <button className="h-icon-btn" onClick={() => setOpen((o) => !o)} aria-label="Settings" aria-expanded={open}>
        <i className="ti ti-settings" style={{ fontSize: 15 }} />
      </button>
      {open && (
        <div className="h-popover" style={{ position: "absolute", top: 40, right: 0, display: "flex", flexDirection: "column", gap: 6, zIndex: 30, minWidth: 168 }}>
          <div style={{ display: "flex", gap: 6 }}>
            {swatch("light", "sun")}
            {swatch("dark", "moon")}
          </div>
          <Link
            href="/admin"
            className="h-menu-item"
            style={{ textDecoration: "none" }}
            onClick={() => setOpen(false)}
            data-testid="settings-admin"
          >
            <i className="ti ti-shield-lock" style={{ fontSize: 15 }} />
            Admin console
          </Link>
        </div>
      )}
    </div>
  )
}
