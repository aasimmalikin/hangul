"use client"

import Link from "next/link"
import { useRef, useState } from "react"
import {
  announceBrands, api, BRAND_SAVED_EVENT, colorOf, fileUrl, FONT_STACK, isRefusal,
  type Brand, type BrandColor, type Look, type Refusal, type Suggestion,
} from "@/lib/brands"

export { BRAND_SAVED_EVENT, colorOf, FONT_STACK }
export type { Brand, BrandColor, Look, Suggestion }

/**
 * The brand-kit wizard: four short, friendly steps with a live preview.
 *   1. "What's your business called?" + one line about it (example chips)
 *   2. "Pick a vibe": three looks drawn as real posts with their name on them
 *   3. "Make it yours": logo (its colours offered back), colours, @handle, website
 *   4. "Your brand kit is ready 🎉" -> make the first post / upload photos
 * Used on /brands and inline in chat (the `brands` tool's setup card).
 */

const EXAMPLES = ["A cosy café in Srinagar", "A bridal boutique", "A dental clinic", "JEE coaching classes", "A home bakery", "A unisex salon"]
// the preview before any look is picked: Hangul's own chinar palette
const STARTER: BrandColor[] = [{ role: "primary", hex: "#A8402C" }, { role: "secondary", hex: "#F6F1EA" }, { role: "accent", hex: "#C9A227" }, { role: "text", hex: "#2E1F18" }]
const ROLE_NAMES: Record<string, string> = { primary: "Main", secondary: "Background", accent: "Highlight", text: "Text" }

/** A tiny poster in the brand's colours and font: what its posts will feel like. */
export function MiniPoster({ name, colors, font, logo, headline = "Today's special", price = "₹80", logoVersion }: {
  name: string; colors: BrandColor[]; font: string; logo?: string; headline?: string; price?: string; logoVersion?: string | null
}) {
  const primary = colorOf(colors, "primary"), secondary = colorOf(colors, "secondary", "#F6F1EA"), accent = colorOf(colors, "accent", primary)
  return (
    <div aria-hidden style={{ aspectRatio: "4 / 5", borderRadius: 12, overflow: "hidden", background: secondary, display: "flex", flexDirection: "column", position: "relative" }}>
      <div style={{ flex: 1, position: "relative", background: `radial-gradient(circle at 50% 45%, ${secondary} 0 18%, ${primary}cc 19% 27%, transparent 28%), linear-gradient(160deg, ${accent}aa, ${primary}88)` }}>
        <span className="h-mini-price" style={{ position: "absolute", top: 10, left: 10, background: accent, color: secondary, fontWeight: 800, fontSize: 11, padding: "3px 8px", borderRadius: 999 }}>{price}</span>
        {logo
          // eslint-disable-next-line @next/next/no-img-element -- the user's own logo behind the BFF
          ? <img src={fileUrl(logo, logoVersion)} alt="" style={{ position: "absolute", top: 8, right: 8, width: 30, height: 30, objectFit: "contain", background: secondary, borderRadius: 6, padding: 2 }} />
          : <span style={{ position: "absolute", top: 9, right: 9, width: 24, height: 24, borderRadius: "50%", background: primary, border: `2px solid ${secondary}` }} />}
      </div>
      <div style={{ background: primary, color: secondary, padding: "9px 11px", fontFamily: FONT_STACK[font] ?? FONT_STACK.sans }}>
        <div style={{ fontSize: 16, fontWeight: 700, lineHeight: 1.1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{headline}</div>
        <div style={{ fontSize: 10.5, opacity: 0.85, fontFamily: FONT_STACK.sans, marginTop: 2, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{name || "Your brand"}</div>
      </div>
    </div>
  )
}

export function Swatches({ colors, size = 16 }: { colors: BrandColor[]; size?: number }) {
  return (
    <span style={{ display: "inline-flex", gap: 4 }}>
      {colors.map((c) => (
        <span key={c.role} title={`${ROLE_NAMES[c.role] ?? c.role} ${c.hex}`}
          style={{ width: size, height: size, borderRadius: size / 4, background: c.hex, border: "0.5px solid var(--surface-border)" }} />
      ))}
    </span>
  )
}

function Celebrate() {
  const bits = Array.from({ length: 18 }, (_, i) => {
    const a = (i / 18) * Math.PI * 2
    return { dx: `${Math.cos(a) * (110 + (i % 3) * 30)}px`, dy: `${Math.sin(a) * (120 + (i % 4) * 20)}px`, delay: `${(i % 6) * 40}ms`,
             bg: ["var(--brand)", "var(--ok)", "var(--muted)"][i % 3] }
  })
  return (
    <span className="h-celebrate-dots" aria-hidden>
      {bits.map((b, i) => <i key={i} style={{ "--dx": b.dx, "--dy": b.dy, animationDelay: b.delay, background: b.bg } as React.CSSProperties} />)}
    </span>
  )
}

export function BrandSetup({ onSaved, onCancel, initialSentence = "", initialSuggestion, compact = false }: {
  onSaved?: (b: Brand) => void; onCancel?: () => void; initialSentence?: string; initialSuggestion?: Suggestion; compact?: boolean
}) {
  // the agent's `brands` tool may already have suggested looks: start at "Pick a vibe"
  const [step, setStep] = useState<1 | 2 | 3 | 4>(initialSuggestion ? 2 : 1)
  const [name, setName] = useState(initialSuggestion?.name ?? "")
  const [sentence, setSentence] = useState(initialSentence)
  const [sug, setSug] = useState<Suggestion | null>(initialSuggestion ?? null)
  const [picked, setPicked] = useState<Look | null>(null)
  const [brand, setBrand] = useState<Brand | null>(null)
  const [colors, setColors] = useState<BrandColor[]>([])
  const [handle, setHandle] = useState("")
  const [website, setWebsite] = useState("")
  const [found, setFound] = useState<BrandColor[] | null>(null)
  const [busy, setBusy] = useState(false)
  const [over, setOver] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [refusal, setRefusal] = useState<Refusal | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  const previewColors = colors.length ? colors : picked?.colors ?? sug?.looks[0]?.colors ?? STARTER
  const previewFont = picked?.font ?? sug?.looks[0]?.font ?? "serif"

  const ask = async () => {
    if (!name.trim()) { setError("What's your business called?"); return }
    setBusy(true); setError(null)
    const s = await api.suggest(sentence.trim().length >= 2 ? `${name}. ${sentence}` : name)
    setBusy(false)
    if (isRefusal(s)) { setError(s.detail); return }
    setSug(s)
    setStep(2)
  }

  const pick = async (look: Look) => {
    setPicked(look); setBusy(true); setError(null); setRefusal(null)
    const custom = look.id.startsWith("custom-")
    const body = custom
      ? { name: name.trim(), look: look.id, kind: sug?.kind, colors: look.colors, style: look.style, voice: look.voice, font: look.font }
      : { name: name.trim(), look: look.id }
    const b = brand ? await api.patch(brand.id, { ...body, colors: look.colors } as Partial<Brand>) : await api.create(body)
    setBusy(false)
    if (isRefusal(b)) { if (b.code === "brand_limit" || b.code === "plan_required") setRefusal(b); else setError(b.detail); return }
    setBrand(b); setColors(b.colors)
    setStep(3)
  }

  const uploadLogo = async (file: File) => {
    if (!brand) return
    setBusy(true); setError(null)
    const r = await api.logo(brand.id, file)
    setBusy(false)
    if (isRefusal(r)) { setError(r.detail); return }
    if (r.brand) setBrand(r.brand)
    setFound(r.suggested_colors?.length === 4 ? r.suggested_colors : null)
  }

  const finish = async () => {
    if (!brand) return
    setBusy(true); setError(null)
    const b = await api.patch(brand.id, { colors, handle, website } as Partial<Brand>)
    setBusy(false)
    if (isRefusal(b)) { setError(b.detail); return }
    setBrand(b)
    setStep(4)
    onSaved?.(b)
    announceBrands(b)
  }

  const progress = (
    <div className="h-wizard-progress" aria-label={`Step ${step} of 4`}>
      {[1, 2, 3, 4].map((i) => <span key={i} data-on={i <= step} />)}
    </div>
  )

  return (
    <section className="h-wizard" data-testid="brand-setup" data-wide={!compact && step < 4} style={compact ? { padding: 16 } : undefined}>
      <div style={{ display: "flex", flexDirection: "column", gap: 14, minWidth: 0 }}>
        {progress}

        {step === 1 && (
          <div className="h-wizard-step" key="s1">
            <h2>Let&apos;s make your brand kit</h2>
            <p className="h-wizard-sub">Two quick answers and Hangul designs the rest. You can change anything later.</p>
            <label className="h-field">
              <span>What&apos;s your business called?</span>
              <input className="h-input" data-testid="brand-name" maxLength={80} value={name} autoFocus={!compact}
                onChange={(e) => setName(e.target.value)} placeholder="Chinar Café" />
            </label>
            <label className="h-field">
              <span>Describe it like you&apos;d tell a friend</span>
              <textarea className="h-input" data-testid="brand-sentence" rows={2} maxLength={300} value={sentence}
                onChange={(e) => setSentence(e.target.value)} placeholder="A cosy café in Srinagar, mostly students and tourists"
                onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void ask() } }} />
            </label>
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
              {EXAMPLES.map((x) => (
                <button key={x} type="button" className="h-chip" onClick={() => setSentence(x)}>{x}</button>
              ))}
            </div>
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <button className="h-btn-solid" onClick={() => void ask()} disabled={busy || !name.trim()} data-testid="brand-suggest" style={{ gap: 6 }}>
                {busy ? "Designing looks…" : <>Show me some looks <i className="ti ti-arrow-right" /></>}
              </button>
              {onCancel && <button className="h-btn-ghost" onClick={onCancel}>Not now</button>}
            </div>
          </div>
        )}

        {step === 2 && sug && (
          <div className="h-wizard-step" key="s2">
            <h2>Pick a vibe for {name || sug.name || "your brand"}</h2>
            <p className="h-wizard-sub">Three looks made for a {sug.label.toLowerCase()}. Tap the one that feels like you.</p>
            <div className="h-look-grid">
              {sug.looks.map((lk) => (
                <button key={lk.id} type="button" className="h-look" data-testid="brand-look" aria-pressed={picked?.id === lk.id}
                  onClick={() => void pick(lk)} disabled={busy}>
                  <MiniPoster name={name || sug.name} colors={lk.colors} font={lk.font} />
                  <span style={{ fontSize: 14, fontWeight: 600, lineHeight: 1.2 }}>{lk.label}</span>
                  <Swatches colors={lk.colors} />
                  <span className="h-muted h-look-voice" style={{ fontSize: 12, lineHeight: 1.35 }}>Sounds {lk.voice}</span>
                </button>
              ))}
            </div>
            <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
              {!initialSuggestion && <button className="h-btn-ghost" onClick={() => setStep(1)}><i className="ti ti-arrow-left" /> Back</button>}
              <button className="h-btn-ghost" onClick={() => { setSug(null); setStep(1) }}>None of these feel right</button>
            </div>
          </div>
        )}

        {step === 3 && brand && (
          <div className="h-wizard-step" key="s3">
            <h2>Make it yours</h2>
            <p className="h-wizard-sub">Add your logo and we&apos;ll stamp it on every post, exactly as it is.</p>
            <input ref={fileRef} type="file" accept=".png,.jpg,.jpeg,.webp" hidden data-testid="brand-logo-input"
              onChange={(e) => { const f = e.target.files?.[0]; if (f) void uploadLogo(f); e.target.value = "" }} />
            <button type="button" className="h-drop" data-over={over} onClick={() => fileRef.current?.click()} disabled={busy}
              onDragOver={(e) => { e.preventDefault(); setOver(true) }} onDragLeave={() => setOver(false)}
              onDrop={(e) => { e.preventDefault(); setOver(false); const f = e.dataTransfer.files?.[0]; if (f) void uploadLogo(f) }}>
              {brand.logo
                // eslint-disable-next-line @next/next/no-img-element -- the user's own logo
                ? <img src={fileUrl(brand.logo, brand.updated_at)} alt="Your logo" style={{ maxHeight: 64, maxWidth: 160, objectFit: "contain" }} />
                : <i className="ti ti-photo-up" />}
              <span><b>{brand.logo ? "Change logo" : "Drop your logo here"}</b> or tap to choose · PNG with a clear background looks best</span>
            </button>
            {found && (
              <div data-testid="brand-logo-colors" className="h-surface" style={{ padding: 12, borderRadius: 12, display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", fontSize: 14 }}>
                <span>✨ We found these colours in your logo</span>
                <Swatches colors={found} size={20} />
                <span style={{ display: "flex", gap: 6, marginLeft: "auto" }}>
                  <button className="h-btn-solid" onClick={() => { setColors(found); setFound(null) }}>Use them</button>
                  <button className="h-btn-ghost" onClick={() => setFound(null)}>Keep the look&apos;s</button>
                </span>
              </div>
            )}
            <div className="h-field">
              <span>Your colours</span>
              <div className="h-kit-colors">
                {colors.map((c, i) => (
                  <label key={c.role} className="h-kit-color">
                    <input type="color" value={c.hex} aria-label={`${ROLE_NAMES[c.role] ?? c.role} colour`}
                      onChange={(e) => setColors((cs) => cs.map((x, j) => (j === i ? { ...x, hex: e.target.value.toUpperCase() } : x)))} />
                    {ROLE_NAMES[c.role] ?? c.role}
                  </label>
                ))}
              </div>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 10 }}>
              <label className="h-field">
                <span>Instagram handle <small>(optional)</small></span>
                <input className="h-input" data-testid="brand-handle" value={handle} maxLength={60} onChange={(e) => setHandle(e.target.value)} placeholder="@chinarcafe" />
              </label>
              <label className="h-field">
                <span>Website or order link <small>(optional)</small></span>
                <input className="h-input" value={website} maxLength={200} onChange={(e) => setWebsite(e.target.value)} placeholder="chinarcafe.in" />
              </label>
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              <button className="h-btn-solid" onClick={() => void finish()} disabled={busy} data-testid="brand-done" style={{ gap: 6 }}>
                {busy ? "Saving…" : <>Finish my brand kit <i className="ti ti-sparkles" /></>}
              </button>
              <button className="h-btn-ghost" onClick={() => setStep(2)}><i className="ti ti-arrow-left" /> Back</button>
            </div>
          </div>
        )}

        {step === 4 && brand && (
          <div className="h-wizard-step h-celebrate" key="s4" data-testid="brand-saved">
            <h2>{brand.name} is ready 🎉</h2>
            <p className="h-wizard-sub" style={{ margin: 0 }}>Your colours, font and logo are saved. Every post you make now looks like you.</p>
            <div className="h-celebrate-poster">
              <Celebrate />
              <MiniPoster name={brand.name} colors={brand.colors} font={brand.font} logo={brand.logo || undefined} logoVersion={brand.updated_at} />
            </div>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", justifyContent: "center" }}>
              <Link href={`/brands/${brand.id}`} className="h-btn-solid" data-testid="brand-first-post" style={{ textDecoration: "none", gap: 6 }}>
                <i className="ti ti-wand" /> Make your first post
              </Link>
              <Link href={`/brands/${brand.id}?tab=photos`} className="h-btn-ghost" style={{ textDecoration: "none", gap: 6 }}>
                <i className="ti ti-photo-plus" /> Upload photos
              </Link>
            </div>
          </div>
        )}

        {refusal && (
          <div data-testid="brand-limit" className="h-surface" style={{ padding: 12, borderRadius: 12, display: "flex", flexDirection: "column", gap: 8, fontSize: 14 }}>
            <span>{refusal.detail}</span>
            {refusal.planNeeded
              ? <Link href={`/billing?upgrade=${refusal.planNeeded}`} className="h-btn-solid" style={{ alignSelf: "flex-start", textDecoration: "none" }}>See plans</Link>
              : <BuySlotButton />}
          </div>
        )}
        {error && <span role="alert" style={{ color: "var(--err)", fontSize: 13 }}>{error}</span>}
      </div>

      {!compact && step < 4 && (
        <aside className="h-wizard-aside" aria-label="Preview">
          <span className="h-muted" style={{ fontSize: 12, fontWeight: 600, textTransform: "uppercase", letterSpacing: ".06em" }}>Live preview</span>
          {previewColors.length
            ? <MiniPoster name={name} colors={previewColors} font={previewFont} logo={brand?.logo || undefined} logoVersion={brand?.updated_at} />
            : <div style={{ aspectRatio: "4 / 5", borderRadius: 12, background: "var(--surface-hover)", display: "grid", placeItems: "center", color: "var(--muted)", fontSize: 13, textAlign: "center", padding: 16 }}>
                Your first post will appear here as you go
              </div>}
          {handle && <span className="h-muted" style={{ fontSize: 12 }}>@{handle.replace(/^@/, "")}{website ? ` · ${website}` : ""}</span>}
        </aside>
      )}
    </section>
  )
}

/** One-time brand slot: a hosted checkout, like a credit top-up. */
export function BuySlotButton() {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const buy = async () => {
    setBusy(true); setError(null)
    const res = await fetch("/api/billing/checkout", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ product: "brand_slot" }) }).catch(() => null)
    const j = res?.ok ? await res.json().catch(() => null) : null
    if (j?.url) { window.location.href = j.url; return }
    setBusy(false)
    setError("Buying a brand slot isn't available right now.")
  }
  return (
    <span style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <button className="h-btn-solid" onClick={() => void buy()} disabled={busy} data-testid="brand-buy-slot" style={{ alignSelf: "flex-start" }}>
        {busy ? "Opening checkout…" : "Add another brand slot"}
      </button>
      {error && <span style={{ color: "var(--err)", fontSize: 12 }}>{error}</span>}
    </span>
  )
}
