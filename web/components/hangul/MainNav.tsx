"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"

/**
 * The four places in Hangul: Today, Chats, My stuff, You. Tabs in the header
 * on wide screens (`MainNavTabs`), a bottom bar on phones (`BottomNav`). The
 * bottom bar is left off inside a conversation, where the composer needs the
 * bottom of the screen.
 */

const ITEMS = [
  { href: "/", label: "Today", icon: "sun", match: (p: string) => p === "/" },
  { href: "/chat", label: "Chats", icon: "messages", match: (p: string) => p.startsWith("/chat") },
  { href: "/lists", label: "My stuff", icon: "checklist", match: (p: string) => p.startsWith("/lists") },
  { href: "/you", label: "You", icon: "user-circle",
    match: (p: string) => ["/you", "/settings", "/vault", "/billing"].some((x) => p.startsWith(x)) },
]

export function MainNavTabs() {
  const path = usePathname() ?? "/"
  return (
    <nav className="h-nav-tabs" aria-label="Main">
      {ITEMS.map((i) => (
        <Link key={i.href} href={i.href} className="h-nav-tab" aria-current={i.match(path) ? "page" : undefined} data-testid={`nav-${i.label}`}>
          <i className={`ti ti-${i.icon}`} style={{ fontSize: 15 }} />{i.label}
        </Link>
      ))}
    </nav>
  )
}

export function BottomNav() {
  const path = usePathname() ?? "/"
  return (
    <nav className="h-bottom-nav" aria-label="Main">
      {ITEMS.map((i) => (
        <Link key={i.href} href={i.href === "/chat" ? "/chats" : i.href}
          aria-current={i.match(path) || (i.href === "/chat" && path.startsWith("/chats")) ? "page" : undefined}>
          <i className={`ti ti-${i.icon}`} style={{ fontSize: 20 }} />{i.label}
        </Link>
      ))}
    </nav>
  )
}
