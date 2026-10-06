"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { useEffect, useState } from "react"

/**
 * The four places in Hangul: Today, Chats, Kept, You. Tabs in the header
 * on wide screens (`MainNavTabs`), a bottom bar on phones (`BottomNav`). The
 * bottom bar is left off inside a conversation, where the composer needs the
 * bottom of the screen.
 *
 * Kept carries a badge: actions waiting for the user's OK (GET /api/kept/count),
 * and nothing else, so a number there always means "go and look".
 */

const ITEMS = [
  { href: "/", label: "Today", icon: "sun", match: (p: string) => p === "/" },
  { href: "/chat", label: "Chats", icon: "messages", match: (p: string) => p.startsWith("/chat") },
  { href: "/kept", label: "Kept", icon: "bookmark", match: (p: string) => p.startsWith("/kept") || p.startsWith("/lists") },
  { href: "/you", label: "You", icon: "user-circle",
    match: (p: string) => ["/you", "/settings", "/vault", "/billing"].some((x) => p.startsWith(x)) },
]

// One count shared by the tabs and the bottom bar, fetched at most every 30 s.
const KEPT_EVENT = "hangul:kept-changed"
let cached: { at: number; n: number } | null = null
let inflight: Promise<number> | null = null

function fetchCount(force = false): Promise<number> {
  if (!force && cached && Date.now() - cached.at < 30_000) return Promise.resolve(cached.n)
  if (inflight && !force) return inflight
  inflight = fetch("/api/kept/count", { cache: "no-store" })
    .then((r) => (r.ok ? r.json() : { needs_you: 0 }))
    .then((d) => { cached = { at: Date.now(), n: Number(d.needs_you) || 0 }; return cached.n })
    .catch(() => cached?.n ?? 0)
    .finally(() => { inflight = null })
  return inflight
}

/** Tell the nav that something on the Kept list changed (an approval decided…). */
export function announceKept() {
  cached = null
  if (typeof window !== "undefined") window.dispatchEvent(new Event(KEPT_EVENT))
}

function useNeedsYou(): number {
  const [n, setN] = useState(cached?.n ?? 0)
  const path = usePathname()
  useEffect(() => {
    let live = true
    const refresh = (force = false) => void fetchCount(force).then((v) => { if (live) setN(v) })
    refresh()
    const onChange = () => refresh(true)
    window.addEventListener(KEPT_EVENT, onChange)
    return () => { live = false; window.removeEventListener(KEPT_EVENT, onChange) }
  }, [path])
  return n
}

function Badge({ n }: { n: number }) {
  if (!n) return null
  return <span className="h-nav-badge" data-testid="kept-badge" aria-label={`${n} waiting for you`}>{n > 9 ? "9+" : n}</span>
}

export function MainNavTabs() {
  const path = usePathname() ?? "/"
  const needsYou = useNeedsYou()
  return (
    <nav className="h-nav-tabs" aria-label="Main">
      {ITEMS.map((i) => (
        <Link key={i.href} href={i.href} className="h-nav-tab" aria-current={i.match(path) ? "page" : undefined} data-testid={`nav-${i.label}`}>
          <i className={`ti ti-${i.icon}`} style={{ fontSize: 15 }} />{i.label}
          {i.href === "/kept" && <Badge n={needsYou} />}
        </Link>
      ))}
    </nav>
  )
}

export function BottomNav() {
  const path = usePathname() ?? "/"
  const needsYou = useNeedsYou()
  return (
    <nav className="h-bottom-nav" aria-label="Main">
      {ITEMS.map((i) => (
        <Link key={i.href} href={i.href === "/chat" ? "/chats" : i.href}
          aria-current={i.match(path) || (i.href === "/chat" && path.startsWith("/chats")) ? "page" : undefined}>
          <span style={{ position: "relative", display: "inline-flex" }}>
            <i className={`ti ti-${i.icon}`} style={{ fontSize: 20 }} />
            {i.href === "/kept" && <Badge n={needsYou} />}
          </span>
          {i.label}
        </Link>
      ))}
    </nav>
  )
}
