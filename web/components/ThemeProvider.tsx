"use client"

import { createContext, useCallback, useContext, useSyncExternalStore } from "react"

export type Theme = "light" | "dark"

const KEY = "theme"
const listeners = new Set<() => void>()

function read(): Theme {
  try {
    const t = localStorage.getItem(KEY)
    return t === "light" ? "light" : "dark"
  } catch {
    return "dark"
  }
}

function write(t: Theme) {
  try { localStorage.setItem(KEY, t) } catch { /* private mode, etc. */ }
  document.documentElement.dataset.theme = t
  listeners.forEach((l) => l())
}

function subscribe(l: () => void) {
  listeners.add(l)
  // Follow changes made in another tab too.
  const onStorage = (e: StorageEvent) => { if (e.key === KEY) l() }
  window.addEventListener("storage", onStorage)
  return () => { listeners.delete(l); window.removeEventListener("storage", onStorage) }
}

const ThemeContext = createContext<{ theme: Theme; setTheme: (t: Theme) => void }>({
  theme: "dark",
  setTheme: () => {},
})

/**
 * Source of truth for light/dark. The value lives in localStorage and on
 * `<html data-theme>`; the inline script in app/layout.tsx applies it before
 * first paint, and this store keeps React in sync after hydration.
 */
export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const theme = useSyncExternalStore(subscribe, read, () => "dark" as Theme)
  const setTheme = useCallback((t: Theme) => write(t), [])
  return <ThemeContext.Provider value={{ theme, setTheme }}>{children}</ThemeContext.Provider>
}

export const useTheme = () => useContext(ThemeContext)
