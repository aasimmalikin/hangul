"use client"

import { useCallback, useEffect, useState } from "react"
import { useSession } from "next-auth/react"
import { AppHeader } from "@/components/hangul/AppHeader"
import { SignInModal, type AuthMode } from "@/components/hangul/SignInModal"

/**
 * Customers: the shop's own list of regulars (backend db/customers.py). Add one,
 * search, tap "Came in today", and see this week's birthdays and the regulars who
 * haven't been in for a while. Hangul never messages a customer itself: "Wish" and
 * "Win back" open the chat to draft something the owner sends.
 */
type Customer = { id: number; name: string; phone: string; birthday: string | null; note: string; visits: number; last_visit: string | null }
type Birthday = { customer_id: number; name: string; date: string; in_days: number; turns?: number }
type Away = Customer & { days_away: number }
type Listing = { customers: Customer[]; total: number; birthdays: Birthday[]; lapsed: Away[]; today: string }

const bday = (b: string | null) => {
  if (!b) return ""
  const [m, d] = b.slice(-5).split("-").map(Number)
  return new Date(2000, m - 1, d).toLocaleDateString("en-IN", { day: "numeric", month: "short" })
}

export default function CustomersPage() {
  const { status } = useSession()
  const [signIn, setSignIn] = useState<{ open: boolean; mode: AuthMode }>({ open: false, mode: "signin" })
  const [dismissed, setDismissed] = useState(false)
  const [data, setData] = useState<Listing | null>(null)
  const [q, setQ] = useState("")
  const [form, setForm] = useState({ name: "", phone: "", birthday: "", note: "" })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async (query = "") => {
    const r = await fetch(`/api/customers${query ? `?q=${encodeURIComponent(query)}` : ""}`, { cache: "no-store" }).catch(() => null)
    if (!r?.ok) { setError("Couldn't load your customers right now."); return }
    setError(null)
    setData(await r.json())
  }, [])

  useEffect(() => {
    if (status !== "authenticated") return
    // Fetch-on-sign-in (and on search, debounced); state is set after the await.
    const t = setTimeout(() => void load(q.trim()), q ? 250 : 0)
    return () => clearTimeout(t)
  }, [status, load, q])

  const add = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!form.name.trim() || busy) return
    setBusy(true); setError(null)
    const r = await fetch("/api/customers", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(form) }).catch(() => null)
    const j = await r?.json().catch(() => null)
    setBusy(false)
    if (!r?.ok) { setError(j?.detail ?? "Couldn't save that customer."); return }
    setForm({ name: "", phone: "", birthday: "", note: "" })
    await load(q.trim())
  }

  const act = async (path: string, method: "POST" | "DELETE") => {
    const r = await fetch(path, { method }).catch(() => null)
    if (!r?.ok) setError("That didn't work. Try again.")
    await load(q.trim())
  }

  const ask = (text: string) => { window.location.href = `/chat?q=${encodeURIComponent(text)}` }

  return (
    <main className="h-has-bottom-nav" style={{ minHeight: "100vh", display: "flex", flexDirection: "column" }}>
      <AppHeader onSignIn={() => setSignIn({ open: true, mode: "signin" })} onSignUp={() => setSignIn({ open: true, mode: "signup" })} />
      <SignInModal open={signIn.open || (status === "unauthenticated" && !dismissed)} mode={signIn.mode}
        onClose={() => { setDismissed(true); setSignIn((s) => ({ ...s, open: false })) }} callbackUrl="/customers"
        reason="Sign in to keep your customer list." />
      <div className="h-studio-page" style={{ maxWidth: 760 }} data-testid="customers-page">
        <div className="h-studio-hero">
          <div>
            <h1>Customers</h1>
            <p>Your regulars, their birthdays and when they last came in. You can also tell Hangul in chat or on WhatsApp: &ldquo;add Riya, 98765 43210, birthday 12 March&rdquo;.</p>
          </div>
        </div>

        {data && data.birthdays.length > 0 && (
          <div className="h-studio-panel" data-testid="customers-birthdays">
            <strong><i className="ti ti-cake" /> Birthdays this week</strong>
            {data.birthdays.map((b) => (
              <div key={b.customer_id} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 14 }}>
                <span style={{ flex: 1 }}>{b.name} <span className="h-muted">{b.in_days === 0 ? "today" : bday(b.date)}{b.turns ? ` · turns ${b.turns}` : ""}</span></span>
                <button className="h-btn-ghost" style={{ fontSize: 12 }} onClick={() => ask(`Draft a short, warm birthday message from my shop to my customer ${b.name}, ready to forward on WhatsApp.`)}>Wish</button>
              </div>
            ))}
          </div>
        )}

        {data && data.lapsed.length > 0 && (
          <div className="h-studio-panel" data-testid="customers-lapsed">
            <strong><i className="ti ti-user-question" /> Haven&apos;t been in for a while</strong>
            {data.lapsed.map((c) => (
              <div key={c.id} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 14 }}>
                <span style={{ flex: 1 }}>{c.name} <span className="h-muted">{c.days_away} days · {c.visits} visits before</span></span>
                <button className="h-btn-ghost" style={{ fontSize: 12 }} onClick={() => ask(`Draft a short, friendly "we miss you" WhatsApp message from my shop to my regular customer ${c.name}, who hasn't been in for ${c.days_away} days.`)}>Win back</button>
              </div>
            ))}
          </div>
        )}

        <form className="h-studio-panel" onSubmit={add} data-testid="customer-form">
          <strong>Add a customer</strong>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <input className="h-input" placeholder="Name" aria-label="Name" value={form.name} maxLength={80} required
              onChange={(e) => setForm({ ...form, name: e.target.value })} style={{ flex: "1 1 160px" }} data-testid="customer-name" />
            <input className="h-input" placeholder="Phone (optional)" aria-label="Phone" value={form.phone} maxLength={24} inputMode="tel"
              onChange={(e) => setForm({ ...form, phone: e.target.value })} style={{ flex: "1 1 140px" }} data-testid="customer-phone" />
            <input className="h-input" placeholder="Birthday, e.g. 12 March" aria-label="Birthday" value={form.birthday} maxLength={24}
              onChange={(e) => setForm({ ...form, birthday: e.target.value })} style={{ flex: "1 1 140px" }} data-testid="customer-birthday" />
          </div>
          <input className="h-input" placeholder="Note, e.g. likes masala chai (optional)" aria-label="Note" value={form.note} maxLength={200}
            onChange={(e) => setForm({ ...form, note: e.target.value })} data-testid="customer-note" />
          <button className="h-btn-solid" type="submit" disabled={busy || !form.name.trim()} style={{ alignSelf: "flex-start" }} data-testid="customer-add">
            {busy ? "Saving…" : "Add"}
          </button>
        </form>

        <div className="h-studio-panel">
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            <strong style={{ flex: 1 }}>{data ? `${data.total} customer${data.total === 1 ? "" : "s"}` : "Customers"}</strong>
            <input className="h-input" type="search" placeholder="Search name or number" aria-label="Search customers" value={q}
              onChange={(e) => setQ(e.target.value)} style={{ maxWidth: 240 }} data-testid="customer-search" />
          </div>
          {data && data.customers.length === 0 && (
            <span className="h-muted" data-testid="customers-empty">{q ? "Nobody matches." : "No customers yet. Add your regulars above."}</span>
          )}
          {data?.customers.map((c) => (
            <div key={c.id} style={{ display: "flex", alignItems: "center", gap: 10, padding: "6px 0", borderTop: "1px solid var(--surface-border)" }} data-testid="customer-row">
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 15 }}>{c.name}</div>
                <div className="h-muted" style={{ fontSize: 12 }}>
                  {[c.phone && <a key="p" href={`tel:${c.phone}`}>{c.phone}</a>, c.birthday && `birthday ${bday(c.birthday)}`,
                    c.visits ? `${c.visits} visit${c.visits === 1 ? "" : "s"}${c.last_visit === data.today ? ", today" : c.last_visit ? `, last ${c.last_visit}` : ""}` : "",
                    c.note].filter(Boolean).map((x, i) => <span key={i}>{i > 0 && " · "}{x}</span>)}
                </div>
              </div>
              <button className="h-btn-ghost" style={{ fontSize: 12 }} disabled={c.last_visit === data.today}
                onClick={() => void act(`/api/customers/${c.id}/visit`, "POST")} data-testid="customer-visit">
                {c.last_visit === data.today ? "Here today" : "Came in today"}
              </button>
              <button className="h-btn-ghost" style={{ fontSize: 12 }} aria-label={`Remove ${c.name}`}
                onClick={() => void act(`/api/customers/${c.id}`, "DELETE")} data-testid="customer-remove">
                <i className="ti ti-trash" />
              </button>
            </div>
          ))}
        </div>
        {!data && !error && status === "authenticated" && <span className="h-muted">Loading…</span>}
        {error && <span role="alert" style={{ color: "var(--err)", fontSize: 13 }}>{error}</span>}
      </div>
    </main>
  )
}
