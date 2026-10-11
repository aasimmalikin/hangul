"use client"

import Link from "next/link"
import { useEffect, useRef, useState } from "react"
import { AppHeader } from "@/components/hangul/AppHeader"
import { LivingStag } from "@/components/hangul/LivingStag"
import { SignInModal } from "@/components/hangul/SignInModal"
import { BUSINESS_KINDS } from "@/lib/personas"

/**
 * The pre-registration page (/join): what Hangul is in one breath, a short form
 * (email, then optionally the kind of business, the city and which plan interests
 * you: the trade is how traction is counted, on /admin), and a way
 * to share it once you're in. Joining twice is harmless and looks the same.
 */
const PLANS = [
  { key: "free", label: "Free" },
  { key: "plus", label: "Plus" },
  { key: "pro", label: "Pro" },
] as const
type Interest = (typeof PLANS)[number]["key"]

const WHAT = [
  { icon: "trending-up", title: "Knows tomorrow", text: "Your sales, tomorrow's forecast and a warning before a slow day." },
  { icon: "speakerphone", title: "Fixes slow days", text: "An offer that keeps your margin, as a post in your brand, then a check on whether it worked." },
  { icon: "brand-whatsapp", title: "Lives in WhatsApp", text: "Log sales, set reminders and approve posts where you already are." },
  { icon: "hand-stop", title: "Always asks first", text: "Nothing is posted, sent or booked without your tap." },
]

// Below this the count reads as "nobody's here" rather than social proof.
const SHOW_COUNT_FROM = 50

export function JoinWaitlist({ source }: { source: string }) {
  const [signInOpen, setSignInOpen] = useState(false)
  const [email, setEmail] = useState("")
  const [trade, setTrade] = useState("")
  const [city, setCity] = useState("")
  const [interest, setInterest] = useState<Interest | "">("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState(false)
  const [total, setTotal] = useState<number | null>(null)
  const emailRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    let alive = true
    void fetch("/api/waitlist", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then((j) => { if (alive && typeof j?.total === "number") setTotal(j.total) })
      .catch(() => {})
    return () => { alive = false }
  }, [])

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (busy) return
    setBusy(true); setError(null)
    const r = await fetch("/api/waitlist", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, trade, city: city.trim(), interest, source }),
    }).catch(() => null)
    const j = await r?.json().catch(() => null)
    setBusy(false)
    if (!r?.ok) {
      setError(r?.status === 429 ? "That's a lot of tries. Wait a few minutes and try again." : j?.detail ?? "Couldn't reach Hangul. Try again in a minute.")
      return
    }
    if (typeof j?.total === "number") setTotal(j.total)
    setDone(true)
  }

  const shareUrl = typeof window === "undefined" ? "" : `${window.location.origin}/join?ref=friend`
  const shareText = "I just pre-registered for Hangul, an AI assistant for small businesses that knows your sales and never acts without your tap. 🦌"
  const tweet = `https://x.com/intent/post?text=${encodeURIComponent(shareText)}&url=${encodeURIComponent(shareUrl)}`

  return (
    <main style={{ minHeight: "100vh", display: "flex", flexDirection: "column" }}>
      <AppHeader onSignIn={() => setSignInOpen(true)} bottomNav={false} />
      <div className="h-home" data-testid="join-page">
        <section className="h-home-in h-home-hero">
          <div>
            <h1>Meet Hangul before everyone else.</h1>
            <p className="h-home-lede">
              The assistant for shops, cafés, kitchens and salons: it knows your sales, warns you before a slow day, makes the post to fix it, and never acts without your tap.
            </p>

            {done ? (
              <div className="h-home-card" style={{ gap: 10, maxWidth: 480 }} data-testid="join-done" role="status">
                <span style={{ fontSize: 20, fontWeight: 600 }}>You&apos;re on the list. 🦌</span>
                <span className="h-muted" style={{ fontSize: 15 }}>
                  We&apos;ll email you once, on launch day, with your founding-member perks. Nothing else.
                </span>
                <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginTop: 6 }}>
                  <a className="h-btn-solid h-home-cta" href={tweet} target="_blank" rel="noopener noreferrer" data-testid="join-share">
                    Share on X
                  </a>
                </div>
              </div>
            ) : (
              <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: 16, maxWidth: 480 }} data-testid="join-form">
                <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                  <input
                    ref={emailRef}
                    className="h-input"
                    type="email"
                    required
                    autoComplete="email"
                    placeholder="you@example.com"
                    aria-label="Your email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    maxLength={254}
                    style={{ flex: "1 1 220px", minWidth: 0 }}
                    data-testid="join-email"
                  />
                  <button className="h-btn-solid h-home-cta" type="submit" disabled={busy || !email.includes("@")} data-testid="join-submit">
                    {busy ? "Joining…" : "Pre-register"}
                  </button>
                </div>

                <fieldset style={{ border: 0, padding: 0, margin: 0, display: "flex", flexDirection: "column", gap: 8 }}>
                  <legend className="h-muted" style={{ fontSize: 14, marginBottom: 8 }}>My business <small>(optional)</small></legend>
                  <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                    {BUSINESS_KINDS.map((k) => (
                      <button key={k.key} type="button" className="h-chip" aria-pressed={trade === k.key}
                        onClick={() => setTrade(trade === k.key ? "" : k.key)} data-testid={`join-trade-${k.key}`}>
                        <i className={`ti ti-${k.icon}`} /> {k.label}
                      </button>
                    ))}
                  </div>
                  <input className="h-input" placeholder="City (optional)" aria-label="Your city" value={city}
                    onChange={(e) => setCity(e.target.value)} maxLength={80} style={{ maxWidth: 260 }} data-testid="join-city" />
                </fieldset>

                <fieldset style={{ border: 0, padding: 0, margin: 0, display: "flex", flexDirection: "column", gap: 8 }}>
                  <legend className="h-muted" style={{ fontSize: 14, marginBottom: 8 }}>Most interested in <small>(optional)</small></legend>
                  <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                    {PLANS.map((p) => (
                      <button key={p.key} type="button" className="h-chip" aria-pressed={interest === p.key}
                        onClick={() => setInterest(interest === p.key ? "" : p.key)} data-testid={`join-plan-${p.key}`}>
                        {p.label}
                      </button>
                    ))}
                  </div>
                </fieldset>

                {error && <p role="alert" style={{ color: "var(--err)", fontSize: 14, margin: 0 }} data-testid="join-error">{error}</p>}
                <p className="h-muted" style={{ fontSize: 13, margin: 0 }}>
                  One email at launch with your founding-member perks. No spam. <Link href="/privacy">Privacy</Link>
                </p>
              </form>
            )}

            {total !== null && total >= SHOW_COUNT_FROM && (
              <p className="h-muted" style={{ fontSize: 14, marginTop: 16 }} data-testid="join-count">
                {total.toLocaleString()} people have pre-registered.
              </p>
            )}
          </div>
          <div className="h-home-art">
            <LivingStag size={280} onAsk={() => emailRef.current?.focus()} />
          </div>
        </section>

        <section className="h-home-sec is-alt">
          <div className="h-home-in">
            <div className="h-home-grid cols-4">
              {WHAT.map((w) => (
                <div key={w.title} className="h-home-card">
                  <span className="h-home-ico"><i className={`ti ti-${w.icon}`} /></span>
                  <b>{w.title}</b>
                  <span className="h-muted" style={{ fontSize: 15 }}>{w.text}</span>
                </div>
              ))}
            </div>
          </div>
        </section>
      </div>
      <SignInModal open={signInOpen} onClose={() => setSignInOpen(false)} mode="signin" callbackUrl="/" />
    </main>
  )
}
