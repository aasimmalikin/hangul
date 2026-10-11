"use client"

import { useEffect, useMemo, useState } from "react"
import { colorOf, FONT_STACK, SIZES, type BrandColor, type Post } from "@/lib/brands"

/**
 * The client's side of a review link: the post in every size, its captions,
 * and two buttons. No account, no app chrome: it is the agency's work, shown in
 * the brand's own colours, with a small "made with Hangul" line.
 */
type Page = { brand: { name: string; colors: BrandColor[]; font: string; logo: string | null; handle: string } | null; post: Post; expires_at: string }

export function ReviewByLink({ token }: { token: string }) {
  const [page, setPage] = useState<Page | null>(null)
  const [gone, setGone] = useState<string | null>(null)
  const [size, setSize] = useState<string | null>(null)
  const [slide, setSlide] = useState(0)
  const [mode, setMode] = useState<"choose" | "changes" | "done">("choose")
  const [comment, setComment] = useState("")
  const [name, setName] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<{ status: string; comment: string } | null>(null)

  useEffect(() => {
    let alive = true
    void fetch(`/api/review/${token}`, { cache: "no-store" }).then(async (r) => {
      const j = await r.json().catch(() => null)
      if (!alive) return
      if (r.ok) setPage(j)
      else setGone(j?.detail ?? "This review link has expired or isn't valid.")
    }).catch(() => { if (alive) setGone("Hangul is unreachable right now. Try again in a minute.") })
    return () => { alive = false }
  }, [token])

  const sizes = useMemo(() => Array.from(new Set(page?.post.files.map((f) => f.size) ?? [])), [page])
  const current = size ?? sizes[0]
  const shown = page?.post.files.filter((f) => f.size === current) ?? []
  const file = shown[Math.min(slide, shown.length - 1)]
  const brand = page?.brand
  const primary = brand ? colorOf(brand.colors, "primary") : "var(--brand)"
  const secondary = brand ? colorOf(brand.colors, "secondary", "#FFFFFF") : "var(--bg)"
  const img = (n: string) => `/api/review/${token}/files/${encodeURIComponent(n)}`

  const decide = async (decision: "approve" | "changes") => {
    setBusy(true); setError(null)
    const r = await fetch(`/api/review/${token}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ decision, comment, name }) }).catch(() => null)
    const j = await r?.json().catch(() => null)
    setBusy(false)
    if (!r?.ok) { setError(j?.detail ?? "Couldn't send that. Try again in a moment."); return }
    setResult(j)
    setMode("done")
  }

  if (gone) {
    return (
      <main className="h-review" data-testid="review-gone">
        <h1 className="h-display" style={{ fontSize: 24, margin: "24px 0 0" }}>This link has ended</h1>
        <p className="h-muted">{gone}</p>
      </main>
    )
  }
  if (!page) return <main className="h-review"><p className="h-muted">Opening the post…</p></main>

  const p = page.post
  const already = p.review_status === "approved" || p.review_status === "changes"
  return (
    <main className="h-review" data-testid="review-page">
      <header style={{ display: "flex", alignItems: "center", gap: 12, padding: "14px 16px", borderRadius: 16, background: primary, color: secondary }}>
        {brand?.logo && (
          // eslint-disable-next-line @next/next/no-img-element -- the brand's logo, served for this link only
          <img src={img(brand.logo)} alt="" style={{ width: 44, height: 44, objectFit: "contain", borderRadius: 10, background: secondary, padding: 3 }} />
        )}
        <div>
          <div style={{ fontFamily: FONT_STACK[brand?.font ?? "sans"], fontSize: 20, fontWeight: 700 }}>{brand?.name ?? "A post"}</div>
          <div style={{ fontSize: 13, opacity: 0.85 }}>A {p.kind === "carousel" ? "carousel" : "post"} for your approval</div>
        </div>
      </header>

      {sizes.length > 1 && (
        <div className="h-studio-tabs" role="tablist" aria-label="Sizes">
          {sizes.map((s) => (
            <button key={s} role="tab" aria-selected={s === current} onClick={() => { setSize(s); setSlide(0) }}>{SIZES.find((x) => x.key === s)?.label ?? s}</button>
          ))}
        </div>
      )}
      {file && (
        // eslint-disable-next-line @next/next/no-img-element -- the post's own file, served for this link only
        <img className="h-result-img" src={img(file.name)} alt={file.label} data-testid="review-img" />
      )}
      {shown.length > 1 && (
        <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 10 }}>
          <button className="h-btn-ghost" aria-label="Previous slide" disabled={slide === 0} onClick={() => setSlide((i) => i - 1)}><i className="ti ti-chevron-left" /></button>
          <span className="h-muted" style={{ fontSize: 13 }}>Slide {slide + 1} of {shown.length}</span>
          <button className="h-btn-ghost" aria-label="Next slide" disabled={slide >= shown.length - 1} onClick={() => setSlide((i) => i + 1)}><i className="ti ti-chevron-right" /></button>
        </div>
      )}

      {Object.keys(p.captions).length > 0 && (
        <section className="h-studio-panel" style={{ padding: 14 }}>
          <div className="h-studio-step"><i className="ti ti-message-2" /> Captions</div>
          {Object.entries(p.captions).map(([k, c]) => (
            <div key={k} className="h-caption">
              <div className="h-caption-head">{c.label}</div>
              <p style={{ margin: 0, whiteSpace: "pre-wrap", fontSize: 14 }}>{c.text}</p>
              {c.hashtags.length > 0 && <span style={{ fontSize: 12, color: "var(--link)" }}>{c.hashtags.join(" ")}</span>}
            </div>
          ))}
        </section>
      )}

      <section className="h-studio-panel" style={{ padding: 16 }}>
        {mode === "done" && result
          ? <div data-testid="review-done" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              <strong style={{ fontSize: 17 }}>{result.status === "approved" ? "Approved ✅ Thank you!" : "Thanks, your changes were sent ✏️"}</strong>
              <span className="h-muted" style={{ fontSize: 14 }}>{brand?.name ? `The team behind ${brand.name}` : "The team"} has been told.</span>
            </div>
          : <>
              {already && (
                <span className="h-muted" style={{ fontSize: 13 }}>
                  {p.review_status === "approved" ? "You approved this already." : `You asked for changes: “${p.review_comment}”`} You can answer again.
                </span>
              )}
              <label className="h-field">
                <span>Your name <small>(optional)</small></span>
                <input className="h-input" value={name} maxLength={80} onChange={(e) => setName(e.target.value)} placeholder="Asif" />
              </label>
              {mode === "changes" && (
                <label className="h-field">
                  <span>What should change?</span>
                  <textarea className="h-input" rows={3} maxLength={2000} value={comment} onChange={(e) => setComment(e.target.value)} autoFocus
                    placeholder="Make the logo bigger, and the price should be ₹90" data-testid="review-comment" />
                </label>
              )}
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                {mode === "changes"
                  ? <>
                      <button className="h-btn-solid" disabled={busy || !comment.trim()} onClick={() => void decide("changes")} data-testid="review-send-changes">Send my changes</button>
                      <button className="h-btn-ghost" onClick={() => setMode("choose")}>Back</button>
                    </>
                  : <>
                      <button className="h-btn-solid" disabled={busy} onClick={() => void decide("approve")} data-testid="review-approve" style={{ gap: 6 }}>
                        <i className="ti ti-check" /> Approve
                      </button>
                      <button className="h-btn-ghost" onClick={() => setMode("changes")} data-testid="review-changes" style={{ gap: 6 }}>
                        <i className="ti ti-pencil" /> Request changes
                      </button>
                    </>}
              </div>
            </>}
        {error && <span role="alert" style={{ color: "var(--err)", fontSize: 13 }}>{error}</span>}
      </section>
      <p className="h-muted" style={{ fontSize: 12, textAlign: "center" }}>
        This private link works until {new Date(page.expires_at).toLocaleDateString()}. Made with Hangul.
      </p>
    </main>
  )
}
