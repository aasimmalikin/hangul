"use client"

import Link from "next/link"
import { useEffect, useState } from "react"
import { HangulSigil } from "@/components/HangulSigil"
import { LivingStag } from "@/components/hangul/LivingStag"
import { LEGAL } from "@/lib/legal"

/**
 * The public homepage at hangul.site (signed out), in the Hearth style, for
 * small-business owners: the living stag beside the promise, a shop's day
 * with Hangul, what it can do,
 * "it always asks first", pricing, installing it on a phone, and the legal
 * footer. Every action that needs an account goes through `onStart`, which
 * opens the page's SignInModal; `callbackUrl` is where to land afterwards
 * (pricing sends people on to /billing with the plan highlighted).
 */
type InstallEvent = Event & { prompt: () => Promise<void> }

const DAY = [
  { at: "8:00", ask: "Brief me.", got: "Yesterday you took ₹16,400, 6% up on last week. Tomorrow looks slow. Rent is due on the 5th." },
  { at: "13:00", ask: "Today's sales: 52 bills, 18,200.", got: "Logged for Tuesday, ₹2,100 above break-even. Or just send a photo of the bill book." },
  { at: "19:00", ask: "Tomorrow looks slow.", got: "A chai + samosa combo post in your colours, ready to share. Each sale still leaves about ₹38. Go ahead?" },
  { at: "21:00", ask: "Remind me to pay the milk supplier.", got: "Done. Tomorrow at 9 am, on WhatsApp and your phone." },
]
const FEATURES = [
  { icon: "trending-up", title: "Know tomorrow", text: "Log sales in one message or import from Vyapar, Petpooja or PhonePe. Hangul forecasts tomorrow, festivals and rain included." },
  { icon: "speakerphone", title: "Fix a slow day", text: "An offer that keeps your margin, made into a post with your logo and colours, then a check on whether it worked." },
  { icon: "brand-whatsapp", title: "All on WhatsApp", text: "Log sales, set reminders and approve posts from the app you already use. Voice notes and photos work too." },
  { icon: "users", title: "Customers and promises", text: "Your regulars, their birthdays, and what you promised customers and suppliers, kept track of for you." },
  { icon: "rocket", title: "Starting out?", text: "A launch plan with what it costs, checked prices, nearby suppliers and your break-even." },
  { icon: "lock", title: "Private by design", text: "Your data isn't sold or used to train AI. Connected-app tokens stay encrypted." },
]

type Pricing = { region: "in" | "intl"; trialDays: number; label: Record<"free" | "plus" | "pro", string> }

/** The visitor's prices: Indian (₹) or international ($) by the device timezone,
 * from GET /api/billing/prices so they match what checkout will charge. If the
 * backend can't be reached, the page guesses from the timezone alone. Null until
 * known, so no one ever sees the other currency flash first. */
function usePricing(): Pricing | null {
  const [p, setP] = useState<Pricing | null>(null)
  useEffect(() => {
    let tz = ""
    try { tz = Intl.DateTimeFormat().resolvedOptions().timeZone ?? "" } catch { /* very old browser */ }
    const india = tz === "Asia/Kolkata" || tz === "Asia/Calcutta"
    const guess: Pricing = { region: india ? "in" : "intl", trialDays: 7,
      label: india ? { free: "₹0", plus: "₹499", pro: "₹1,499" } : { free: "$0", plus: "$20", pro: "$100" } }
    let alive = true
    fetch(`/api/billing/prices?tz=${encodeURIComponent(tz)}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((d: { region: "in" | "intl"; trial_days: number; plans: Array<{ id: string; prices?: { month?: { label: string } } }> }) => {
        const of = (id: string, fallback: string) => d.plans.find((x) => x.id === id)?.prices?.month?.label ?? fallback
        const zero = d.region === "in" ? "₹0" : "$0"
        if (alive) setP({ region: d.region, trialDays: d.trial_days, label: { free: of("free", zero), plus: of("plus", guess.label.plus), pro: of("pro", guess.label.pro) } })
      })
      .catch(() => { if (alive) setP(guess) })
    return () => { alive = false }
  }, [])
  return p
}

function useInstall() {
  const [evt, setEvt] = useState<InstallEvent | null>(null)
  useEffect(() => {
    const on = (e: Event) => { e.preventDefault(); setEvt(e as InstallEvent) }
    window.addEventListener("beforeinstallprompt", on)
    return () => window.removeEventListener("beforeinstallprompt", on)
  }, [])
  return evt
}

export function HomeLanding({ onStart }: { onStart: (reason?: string, callbackUrl?: string) => void }) {
  const install = useInstall()
  const pricing = usePricing()
  const price = (k: "free" | "plus" | "pro") => pricing?.label[k] ?? "\u00a0"       // blank until the currency is known
  const trial = pricing?.trialDays ?? 0
  const start = () => onStart()

  return (
    <div className="h-home" data-testid="home-landing">
      <section className="h-home-in h-home-hero">
        <div>
          <h1>Your shop&apos;s own assistant. It knows your sales and gets things done.</h1>
          <p className="h-home-lede">Hangul keeps your sales, customers and reminders, tells you when tomorrow will be slow, makes the post to fix it, and always asks before it does anything.</p>
          <div className="h-home-ctas">
            <button className="h-btn-solid h-home-cta" onClick={start} data-testid="home-start">Start free</button>
            <a className="h-btn-outline h-home-cta" href="#day" data-testid="home-see-day">See a day with Hangul</a>
          </div>
          <p className="h-muted" style={{ fontSize: 14, margin: "16px 0 0" }}>Free to start · Works on WhatsApp and any phone, no app store needed</p>
        </div>
        <div className="h-home-art">
          <LivingStag size={300} onAsk={() => onStart("Create your free account and Hangul will do that for you.")} />
        </div>
      </section>

      <section className="h-home-sec" id="day">
        <div className="h-home-in">
          <h2>A day with Hangul</h2>
          <p className="h-home-sub">A café owner&apos;s day. It learns your routine, so the right thing is one tap away.</p>
          <div className="h-home-grid cols-4">
            {DAY.map((d) => (
              <div key={d.at} className="h-home-card">
                <span className="h-home-time">{d.at}</span>
                <span className="h-home-quote">&ldquo;{d.ask}&rdquo;</span>
                <span className="h-muted" style={{ fontSize: 14 }}>{d.got}</span>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="h-home-sec is-alt" id="features">
        <div className="h-home-in">
          <h2>Built for shops, cafés, kitchens and salons</h2>
          <p className="h-home-sub">Start with WhatsApp. Connect Google when you want email and calendar too.</p>
          <div className="h-home-grid cols-3">
            {FEATURES.map((f) => (
              <div key={f.title} className="h-home-card">
                <span className="h-home-ico"><i className={`ti ti-${f.icon}`} /></span>
                <b style={{ fontSize: 17, fontWeight: 600, marginTop: 8 }}>{f.title}</b>
                <span className="h-muted" style={{ fontSize: 15 }}>{f.text}</span>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="h-home-sec">
        <div className="h-home-in h-home-two">
          <div>
            <h2>It always asks first</h2>
            <p className="h-home-sub" style={{ marginBottom: 16 }}>Hangul prepares, you decide. No offer, email or booking goes out without your tap.</p>
            <ul style={{ margin: 0, paddingLeft: 20, display: "flex", flexDirection: "column", gap: 8, fontSize: 16, listStyle: "disc" }}>
              <li>See exactly what will be sent before it goes</li>
              <li>Approve on the web, on your phone or in WhatsApp</li>
              <li>Hangul never posts or messages your customers by itself</li>
            </ul>
          </div>
          <div className="h-home-card" style={{ gap: 10 }} aria-label="Example: a slow-day offer waiting for approval">
            <span className="h-stag-who">Waiting for you · Tomorrow&apos;s offer</span>
            <div style={{ border: "1px solid var(--surface-border)", borderRadius: 10, padding: "12px 14px", fontSize: 14.5, display: "flex", flexDirection: "column", gap: 4 }}>
              <span><span className="h-muted">Why</span> Wednesday looks like ₹9,800, under your break-even of ₹11,500</span>
              <span><span className="h-muted">Offer</span> Chai + samosa combo, ₹60</span>
              <span style={{ marginTop: 6 }}>A post and a story in your colours, with a message ready to forward. Each sale still leaves about ₹38.</span>
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              <span className="h-btn-solid" aria-hidden>Go ahead</span><span className="h-btn-outline" aria-hidden>Not this time</span>
            </div>
          </div>
        </div>
      </section>

      <section className="h-home-sec is-alt" id="pricing">
        <div className="h-home-in">
          <h2>Simple pricing</h2>
          <p className="h-home-sub">Start free. Upgrade when Hangul starts paying for itself.</p>
          <div className="h-home-grid cols-3">
            <div className="h-home-card" style={{ gap: 10 }}>
              <b style={{ fontSize: 17 }}>Free</b><span className="h-home-price" data-testid="home-price-free">{price("free")}</span>
              <ul className="h-muted" style={{ margin: 0, paddingLeft: 18, listStyle: "disc", flex: 1, fontSize: 15 }}>
                <li>Log and import sales, see your week</li><li>Reminders, customers and promises, on WhatsApp too</li><li>A launch plan for a new business</li>
              </ul>
              <button className="h-btn-outline" onClick={start} data-testid="home-plan-free">Start free</button>
            </div>
            <div className="h-home-card is-best" style={{ gap: 10 }}>
              <span className="h-home-tag">{trial > 0 ? `Most popular · ${trial} days free` : "Most popular"}</span>
              <b style={{ fontSize: 17 }}>Plus</b>
              <span className="h-home-price" data-testid="home-price-plus">{price("plus")}<span className="h-muted" style={{ fontSize: 15, fontFamily: "inherit" }}> /month</span></span>
              <ul className="h-muted" style={{ margin: 0, paddingLeft: 18, listStyle: "disc", flex: 1, fontSize: 15 }}>
                <li>Tomorrow&apos;s forecast and slow-day warnings</li><li>A slow day handled each week, posts in your brand</li><li>Daily brief, email and calendar, the full WhatsApp</li>
              </ul>
              <button className="h-btn-solid" onClick={() => onStart(trial > 0 ? `Create your account, then start your ${trial}-day free trial of Plus.` : "Create your account, then choose Plus.", "/billing?upgrade=plus")} data-testid="home-plan-plus">{trial > 0 ? "Try Plus free" : "Choose Plus"}</button>
            </div>
            <div className="h-home-card" style={{ gap: 10 }}>
              <b style={{ fontSize: 17 }}>Pro</b>
              <span className="h-home-price" data-testid="home-price-pro">{price("pro")}<span className="h-muted" style={{ fontSize: 15, fontFamily: "inherit" }}> /month</span></span>
              <ul className="h-muted" style={{ margin: 0, paddingLeft: 18, listStyle: "disc", flex: 1, fontSize: 15 }}>
                <li>Every slow day handled, and why it&apos;s slow</li><li>Up to 5 businesses and 3 brands</li><li>Photo edits, carousels and client review links</li>
              </ul>
              <button className="h-btn-outline" onClick={() => onStart("Create your account, then choose Pro.", "/billing?upgrade=pro")} data-testid="home-plan-pro">Choose Pro</button>
            </div>
          </div>
        </div>
      </section>

      <section className="h-home-sec" id="install">
        <div className="h-home-in">
          <h2>On your phone in ten seconds</h2>
          <p className="h-home-sub">No app store. Hangul installs straight from your browser and opens like any other app.</p>
          <div className="h-home-grid cols-3">
            <div className="h-home-card">
              <span style={{ width: 64, height: 64, borderRadius: 16, background: "var(--brand)", display: "grid", placeItems: "center", ["--sigil" as string]: "var(--solid-fg)" }}>
                <HangulSigil size={46} />
              </span>
              <b style={{ fontSize: 17, marginTop: 8 }}>This is the icon</b>
              <span className="h-muted" style={{ fontSize: 15 }}>Press and hold it for &ldquo;Talk to Hangul&rdquo;.</span>
              {install && (
                <button className="h-btn-solid" style={{ alignSelf: "flex-start", marginTop: 6 }} data-testid="home-install"
                  onClick={() => void install.prompt()}>Install Hangul</button>
              )}
            </div>
            <div className="h-home-card">
              <b style={{ fontSize: 17 }}>Android</b>
              <ol className="h-muted" style={{ margin: 0, paddingLeft: 20, listStyle: "decimal", fontSize: 15 }}><li>Open hangul.site in Chrome</li><li>Tap <b>Install</b></li></ol>
            </div>
            <div className="h-home-card">
              <b style={{ fontSize: 17 }}>iPhone</b>
              <ol className="h-muted" style={{ margin: 0, paddingLeft: 20, listStyle: "decimal", fontSize: 15 }}><li>Open hangul.site in Safari</li><li>Share → <b>Add to Home Screen</b></li></ol>
            </div>
          </div>
        </div>
      </section>

      <footer className="h-home-in h-home-foot">
        <nav aria-label="Legal" data-testid="landing-legal" style={{ display: "flex", gap: 18, flexWrap: "wrap" }}>
          <Link href="/terms">Terms</Link><Link href="/privacy">Privacy</Link><Link href="/refunds">Refunds</Link>
          <span>{LEGAL.contactEmail}</span>
        </nav>
        <span>© {new Date().getFullYear()} Hangul</span>
      </footer>
    </div>
  )
}
