"use client"

import Link from "next/link"
import { useCallback, useEffect, useState } from "react"
import { useSession } from "next-auth/react"
import { AppHeader } from "@/components/hangul/AppHeader"
import { SignInModal, type AuthMode } from "@/components/hangul/SignInModal"
import { BrandSetup, BuySlotButton, MiniPoster, Swatches } from "@/components/hangul/BrandSetup"
import { BrandSample } from "@/components/hangul/BrandPreview"
import { api, FONT_STACK, fileUrl, isRefusal, type Brand, type Listing } from "@/lib/brands"

/**
 * Brand Studio home: every brand as a card showing a real post in its look,
 * a "+ New brand" card, and the wizard opening in place. Plans include some
 * brands (Plus 1, Pro 3); more are one-time slots. Brands past the limit after a
 * downgrade are paused, never deleted.
 */
const EXAMPLES = [
  { name: "Chinar Café", headline: "Monday special", price: "₹80", font: "serif",
    colors: [{ role: "primary", hex: "#A8402C" }, { role: "secondary", hex: "#F3E6D3" }, { role: "accent", hex: "#C9A227" }, { role: "text", hex: "#2E1F18" }] },
  { name: "Zara Boutique", headline: "New arrivals", price: "30% OFF", font: "display",
    colors: [{ role: "primary", hex: "#D81B60" }, { role: "secondary", hex: "#FFF3F8" }, { role: "accent", hex: "#FFC107" }, { role: "text", hex: "#1A1A1A" }] },
  { name: "Smile Dental", headline: "Free check-up", price: "Sat only", font: "sans",
    colors: [{ role: "primary", hex: "#1565C0" }, { role: "secondary", hex: "#F3F8FD" }, { role: "accent", hex: "#26A69A" }, { role: "text", hex: "#10263D" }] },
]

function BrandCard({ b, onRemove }: { b: Brand; onRemove: (id: number) => void }) {
  const [confirm, setConfirm] = useState(false)
  return (
    <article style={{ display: "flex", flexDirection: "column", gap: 6, opacity: b.paused ? 0.6 : 1 }} data-testid="brand-card">
      <Link href={b.paused ? "/billing" : `/brands/${b.id}`} className="h-brand-card" aria-label={`Open ${b.name}`}>
        <div className="h-brand-card-cover">
          {b.cover
            // eslint-disable-next-line @next/next/no-img-element -- the user's own post
            ? <img src={fileUrl(b.cover)} alt="" />
            : <BrandSample brandId={b.id} name={b.name} version={b.updated_at} />}
          {b.paused && <span className="h-badge" data-testid="brand-paused" style={{ position: "absolute", top: 10, left: 10 }}>Paused</span>}
        </div>
        <div className="h-brand-card-body">
          <span className="h-brand-card-name" style={{ fontFamily: FONT_STACK[b.font] ?? FONT_STACK.sans }}>{b.name}</span>
          <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <Swatches colors={b.colors} size={14} />
            <span className="h-muted" style={{ fontSize: 12, marginLeft: "auto" }}>{b.posts ? `${b.posts} post${b.posts === 1 ? "" : "s"}` : "No posts yet"}</span>
          </span>
        </div>
      </Link>
      <div style={{ display: "flex", gap: 6, justifyContent: "flex-end", minHeight: 28 }}>
        {b.paused && <span style={{ fontSize: 12, marginRight: "auto" }}>Over your plan&apos;s brands</span>}
        {confirm
          ? <>
              <button className="h-btn-ghost" style={{ fontSize: 12, color: "var(--err)" }} onClick={() => onRemove(b.id)} data-testid="brand-hide-confirm">Yes, remove</button>
              <button className="h-btn-ghost" style={{ fontSize: 12 }} onClick={() => setConfirm(false)}>Keep</button>
            </>
          : <button className="h-btn-ghost" style={{ fontSize: 12 }} onClick={() => setConfirm(true)} data-testid="brand-hide" aria-label={`Remove ${b.name}`}>
              <i className="ti ti-trash" />
            </button>}
      </div>
    </article>
  )
}

export default function BrandsPage() {
  const { status } = useSession()
  const [signIn, setSignIn] = useState<{ open: boolean; mode: AuthMode }>({ open: false, mode: "signin" })
  const [dismissed, setDismissed] = useState(false)
  const [data, setData] = useState<Listing | null>(null)
  const [adding, setAdding] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    const r = await api.brands()
    if (isRefusal(r)) setError("Couldn't load your brands right now.")
    else setData(r)
  }, [])

  useEffect(() => {
    if (status !== "authenticated") return
    // Fetch-on-sign-in; state is set after the await.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load()
  }, [status, load])

  const remove = async (id: number) => {
    const res = await api.remove(id)
    if (res?.ok) void load()
    else setError("Couldn't remove that brand. Try again in a moment.")
  }

  const empty = data && data.brands.length === 0
  return (
    <main className="h-has-bottom-nav" style={{ minHeight: "100vh", display: "flex", flexDirection: "column" }}>
      <AppHeader onSignIn={() => setSignIn({ open: true, mode: "signin" })} onSignUp={() => setSignIn({ open: true, mode: "signup" })} />
      <SignInModal open={signIn.open || (status === "unauthenticated" && !dismissed)} mode={signIn.mode}
        onClose={() => { setDismissed(true); setSignIn((s) => ({ ...s, open: false })) }} callbackUrl="/brands" reason="Sign in to open your Brand Studio." />
      <div className="h-studio-page">
        <div className="h-studio-hero">
          <div>
            <h1>Brand Studio</h1>
            <p>Your photos, your colours, your logo: posts for every platform in a minute, with captions written in your voice.</p>
          </div>
          {data && data.slots > 0 && (
            <span className="h-badge" data-testid="brand-slots">
              {data.used} of {data.slots} brand{data.slots === 1 ? "" : "s"} used
            </span>
          )}
        </div>

        {adding && <BrandSetup onSaved={() => void load()} onCancel={() => setAdding(false)} />}

        {empty && !adding && (
          <section className="h-studio-panel h-empty-hero" data-testid="brand-empty" style={{ padding: 22 }}>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 10 }}>
              {EXAMPLES.map((x, i) => (
                <div key={x.name} style={{ transform: `rotate(${(i - 1) * 3}deg) translateY(${i === 1 ? -8 : 0}px)` }}>
                  <MiniPoster name={x.name} colors={x.colors} font={x.font} headline={x.headline} price={x.price} />
                </div>
              ))}
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 14, alignItems: "flex-start" }}>
            <div>
              <h2 className="h-display" style={{ fontSize: 26, margin: "0 0 6px" }}>This could be your business</h2>
              <p className="h-muted" style={{ margin: 0, fontSize: 14 }}>
                Set up your brand kit once. Then drop in a photo and get a ready-to-post image in every size, with your logo and words spelled right.
              </p>
            </div>
            {data.slots === 0
              ? <Link href="/billing?upgrade=plus" className="h-btn-solid" style={{ alignSelf: "flex-start", textDecoration: "none" }} data-testid="brand-upgrade">
                  Brands come with Plus and Pro · See plans
                </Link>
              : <button className="h-btn-solid h-make-btn" style={{ width: "auto", alignSelf: "flex-start" }} onClick={() => setAdding(true)} data-testid="brand-add">
                  <i className="ti ti-sparkles" /> Create your brand kit — it takes a minute
                </button>}
            <ul className="h-muted" style={{ margin: 0, paddingLeft: 18, fontSize: 13, lineHeight: 1.7 }}>
              <li>8 layouts: offers, events, products, reviews, before/after…</li>
              <li>Every size at once: Instagram, Stories, Facebook, LinkedIn, X, YouTube, Pinterest, print</li>
              <li>Captions with your hashtags, and a link to send your client for approval</li>
            </ul>
            </div>
          </section>
        )}

        {data && data.brands.length > 0 && (
          <>
            <div className="h-studio-section-title">Your brands</div>
            <div className="h-brand-grid">
              {data.brands.map((b) => <BrandCard key={b.id} b={b} onRemove={(id) => void remove(id)} />)}
              {!adding && (data.can_add
                ? <button className="h-brand-card-add" onClick={() => setAdding(true)} data-testid="brand-add">
                    <i className="ti ti-plus" />
                    <b style={{ color: "var(--fg)" }}>New brand</b>
                    <span style={{ fontSize: 13 }}>Another business or a client</span>
                  </button>
                : <div className="h-brand-card-add" style={{ cursor: "default" }} data-testid="brand-full">
                    <i className="ti ti-lock" />
                    <span style={{ fontSize: 13 }}>All your brand slots are in use. Add one more, paid once.</span>
                    <BuySlotButton />
                  </div>)}
            </div>
          </>
        )}
        {error && <span role="alert" style={{ color: "var(--err)", fontSize: 13 }}>{error}</span>}
      </div>
    </main>
  )
}
