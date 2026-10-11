"use client"

import Link from "next/link"
import { useMemo, useState, type Dispatch, type SetStateAction } from "react"
import { PhotoDrop, PhotoGrid } from "@/components/hangul/BrandPhotos"
import { useDesignPreview } from "@/components/hangul/BrandPreview"
import { PostResult } from "@/components/hangul/PostResult"
import {
  api, CAROUSEL_SIZES, isRefusal, LAYOUTS, SIZES, wordLabel,
  type Asset, type Brand, type Post, type Refusal, type WordKey,
} from "@/lib/brands"

/**
 * The Create tab: 1 photo(s) · 2 kind and layout · 3 words · 4 sizes, with a
 * live preview beside it (tap it to keep that spot in frame), then "Make it" ->
 * every size rendered, and the result with captions, ZIP and client review.
 */
type Words = Record<WordKey, string>

function Ratio({ w, h }: { w: number; h: number }) {
  const k = 16 / Math.max(w, h)
  return <span className="h-ratio" style={{ width: Math.round(w * k), height: Math.round(h * k) }} aria-hidden />
}

/** A post to start from (How's business ideas open the studio with one), from the page's URL. */
export type StudioPrefill = { layout?: string; headline?: string; subline?: string; price?: string; cta?: string; from?: string }

export function BrandStudio({ brand, photos, onPhotosChange, onMade, prefill }: {
  brand: Brand; photos: Asset[]; onPhotosChange: Dispatch<SetStateAction<Asset[]>>; onMade: (p: Post) => void
  prefill?: StudioPrefill
}) {
  const [kind, setKind] = useState<"single" | "carousel">("single")
  const [layout, setLayout] = useState(prefill?.layout && LAYOUTS.some((l) => l.key === prefill.layout) ? prefill.layout : "band")
  const [picked, setPicked] = useState<string[]>(photos[0] ? [photos[0].name] : [])
  const [words, setWords] = useState<Words>({
    headline: (prefill?.headline ?? "").slice(0, 160), subline: (prefill?.subline ?? "").slice(0, 200),
    price: (prefill?.price ?? "").slice(0, 24), cta: (prefill?.cta || brand.cta || "").slice(0, 40),
  })
  const [slideWords, setSlideWords] = useState<Record<string, { headline: string; subline: string }>>({})
  const [sizes, setSizes] = useState<string[]>(["post", "portrait", "story"])
  const [previewSize, setPreviewSize] = useState("portrait")
  const [previewSlide, setPreviewSlide] = useState(0)
  const [focus, setFocus] = useState<[number, number]>([0.5, 0.45])
  const [making, setMaking] = useState(false)
  const [made, setMade] = useState<Post | null>(null)
  const [refusal, setRefusal] = useState<Refusal | null>(null)

  const meta = LAYOUTS.find((l) => l.key === layout) ?? LAYOUTS[0]
  const split = kind === "single" && layout === "split"
  const usable = kind === "carousel" ? sizes.filter((s) => CAROUSEL_SIZES.includes(s)) : sizes
  const shownSize = usable.includes(previewSize) ? previewSize : usable[0] ?? "post"

  const pick = (name: string) => {
    setPicked((p) => {
      if (kind === "carousel") return p.includes(name) ? p.filter((x) => x !== name) : p.length >= 10 ? p : [...p, name]
      if (split) return p.includes(name) ? p.filter((x) => x !== name) : [...p.slice(-1), name].slice(-2)
      return [name]
    })
    setFocus([0.5, 0.45])
  }

  const slides = picked.map((image) => ({ image, headline: slideWords[image]?.headline ?? "", subline: slideWords[image]?.subline ?? "" }))
  const design = useMemo(() => kind === "carousel" && picked.length
    ? { layout, slides, slide: Math.min(previewSlide, slides.length), size: shownSize, words: { cta: words.cta }, closing: true }
    : { layout, words, image: picked[0] ?? null, image2: split ? picked[1] ?? null : null, focus, size: shownSize },
  // eslint-disable-next-line react-hooks/exhaustive-deps -- slides is derived from picked + slideWords
  [kind, layout, words, picked, slideWords, split, focus, shownSize, previewSlide])
  const preview = useDesignPreview(brand.id, design)

  const make = async () => {
    setMaking(true); setRefusal(null)
    const body = kind === "carousel"
      ? { layout, slides, sizes: usable.length ? usable : ["portrait"], words: { cta: words.cta }, closing: true }
      : { layout, words, image: picked[0], image2: split ? picked[1] : null, focus, sizes }
    const r = await api.make(brand.id, body)
    setMaking(false)
    if (isRefusal(r)) { setRefusal(r); return }
    setMade(r)
    onMade(r)
  }

  const ready = kind === "carousel" ? picked.length >= 2 : split ? picked.length === 2 : picked.length === 1
  const why = kind === "carousel" ? "Pick 2 to 10 photos, in the order they should appear"
    : split ? "Pick two photos: before, then after" : "Pick a photo"

  return (
    <div className="h-studio-grid">
      <div style={{ display: "flex", flexDirection: "column", gap: 14, minWidth: 0 }}>
        {prefill?.from === "business" && (
          <div className="h-launch-banner" data-testid="studio-from-business">
            <i className="ti ti-trending-up" style={{ fontSize: 18 }} />
            <span>Tomorrow&apos;s idea from <b>How&apos;s business</b> is filled in. Pick a photo, check the words, and make it.</span>
          </div>
        )}
        <section className="h-studio-panel">
          <div className="h-studio-step"><b>1</b> {kind === "carousel" ? "Your photos, in order" : split ? "Before and after photos" : "Your photo"}</div>
          <PhotoDrop brandId={brand.id} compact={photos.length > 0}
            onAdded={(a) => { onPhotosChange((ps) => [a, ...ps]); setPicked((p) => (kind === "single" && !split ? [a.name] : p.length < 10 ? [...p, a.name] : p)) }} />
          <PhotoGrid photos={photos} selected={picked} onPick={pick} numbered={kind === "carousel" || split} />
          {!ready && photos.length > 0 && <span className="h-muted" style={{ fontSize: 13 }}>{why}</span>}
        </section>

        <section className="h-studio-panel">
          <div className="h-studio-step"><b>2</b> What are you making?</div>
          <div className="h-studio-tabs" role="tablist">
            <button role="tab" aria-selected={kind === "single"} onClick={() => { setKind("single"); setPicked((p) => p.slice(0, 1)) }} data-testid="kind-single">Single post</button>
            <button role="tab" aria-selected={kind === "carousel"} onClick={() => { setKind("carousel"); setPreviewSlide(0); if (!sizes.some((s) => CAROUSEL_SIZES.includes(s))) setSizes([...sizes, "portrait"]) }} data-testid="kind-carousel">
              Carousel <span className="h-badge" data-tone="brand" style={{ marginLeft: 4 }}>Pro</span>
            </button>
          </div>
          <div className="h-layout-grid" role="group" aria-label="Layout">
            {LAYOUTS.filter((l) => kind === "single" || l.key !== "split").map((l) => (
              <button key={l.key} className="h-layout-tile" aria-pressed={layout === l.key} title={l.hint} data-testid={`layout-${l.key}`}
                onClick={() => { setLayout(l.key); if (l.key !== "split") setPicked((p) => kind === "single" ? p.slice(0, 1) : p) }}>
                <i className={`ti ti-${l.icon}`} /> {l.label}
              </button>
            ))}
          </div>
          <span className="h-muted" style={{ fontSize: 12.5 }}>{meta.hint}{kind === "carousel" ? ". The first slide uses this layout; the rest are numbered, and a “follow us” slide is added at the end." : "."}</span>
        </section>

        <section className="h-studio-panel">
          <div className="h-studio-step"><b>3</b> The words</div>
          {kind === "carousel"
            ? <>
                {slides.length === 0 && <span className="h-muted" style={{ fontSize: 13 }}>Pick photos above, then write a line for each slide.</span>}
                {slides.map((s, i) => (
                  <div key={s.image} style={{ display: "grid", gridTemplateColumns: "28px 1fr", gap: 8, alignItems: "start" }}>
                    <span className="h-photo-num" style={{ position: "static", marginTop: 8 }}>{i + 1}</span>
                    <div style={{ display: "grid", gap: 6 }}>
                      <input className="h-input" placeholder={i === 0 ? "Cover headline: 5 ways to enjoy kahwa" : "Slide headline"} maxLength={160}
                        value={s.headline} onFocus={() => setPreviewSlide(i)} data-testid="slide-headline"
                        onChange={(e) => setSlideWords((w) => ({ ...w, [s.image]: { ...(w[s.image] ?? { headline: "", subline: "" }), headline: e.target.value } }))} />
                      <input className="h-input" placeholder="A line of detail (optional)" maxLength={200} value={s.subline} onFocus={() => setPreviewSlide(i)}
                        onChange={(e) => setSlideWords((w) => ({ ...w, [s.image]: { ...(w[s.image] ?? { headline: "", subline: "" }), subline: e.target.value } }))} />
                    </div>
                  </div>
                ))}
                <label className="h-field">
                  <span>Last slide&apos;s button</span>
                  <input className="h-input" value={words.cta} maxLength={40} placeholder={brand.cta || "Follow for more"}
                    onFocus={() => setPreviewSlide(slides.length)} onChange={(e) => setWords((w) => ({ ...w, cta: e.target.value }))} />
                </label>
              </>
            : meta.words.map((k) => {
                const { label, placeholder } = wordLabel(layout, k)
                const long = k === "headline" && layout === "quote"
                return (
                  <label key={k} className="h-field">
                    <span>{label}</span>
                    {long
                      ? <textarea className="h-input" rows={3} maxLength={160} value={words[k]} placeholder={placeholder} data-testid={`word-${k}`}
                          onChange={(e) => setWords((w) => ({ ...w, [k]: e.target.value }))} />
                      : <input className="h-input" maxLength={k === "price" ? 24 : k === "cta" ? 40 : 160} value={words[k]} placeholder={placeholder} data-testid={`word-${k}`}
                          onChange={(e) => setWords((w) => ({ ...w, [k]: e.target.value }))} />}
                  </label>
                )
              })}
          {(brand.handle || brand.website || brand.footer) && (
            <span className="h-muted" style={{ fontSize: 12 }}>
              Your {[brand.handle && "handle", brand.website && "website", brand.footer && "footer"].filter(Boolean).join(", ")} go on automatically.{" "}
              <Link href={`/brands/${brand.id}?tab=kit`}>Change</Link>
            </span>
          )}
        </section>

        <section className="h-studio-panel">
          <div className="h-studio-step"><b>4</b> Where will you post it?</div>
          <div className="h-size-row">
            {SIZES.map((s) => {
              const off = kind === "carousel" && !CAROUSEL_SIZES.includes(s.key)
              return (
                <button key={s.key} className="h-size-chip" aria-pressed={sizes.includes(s.key) && !off} disabled={off} title={s.label} data-testid={`size-${s.key}`}
                  onClick={() => setSizes((ss) => ss.includes(s.key) ? ss.filter((x) => x !== s.key) : [...ss, s.key])}>
                  <Ratio w={s.w} h={s.h} /> {s.name}
                </button>
              )
            })}
          </div>
          <span className="h-muted" style={{ fontSize: 12.5 }}>
            Stories keep your words clear of Instagram&apos;s and WhatsApp&apos;s own buttons.
          </span>
        </section>
        {/* on phones the preview sits at the top, so the button is repeated here, at the end of the form */}
        <button className="h-btn-solid h-make-btn h-mobile-only" disabled={!ready || making || (kind === "single" ? sizes.length === 0 : usable.length === 0)}
          onClick={() => void make()}>
          <i className="ti ti-sparkles" /> {making ? "Making every size…" : kind === "carousel" ? `Make the carousel (${slides.length + 1} slides)` : `Make it — ${sizes.length} size${sizes.length === 1 ? "" : "s"}`}
        </button>
      </div>

      <aside className="h-preview" aria-label="Live preview">
        {usable.length > 1 && (
          <div className="h-studio-tabs" role="tablist" aria-label="Preview size">
            {usable.map((s) => (
              <button key={s} role="tab" aria-selected={s === shownSize} onClick={() => setPreviewSize(s)}>{SIZES.find((x) => x.key === s)?.name}</button>
            ))}
          </div>
        )}
        <div className="h-preview-frame" data-busy={preview.busy} data-testid="studio-preview"
          title={kind === "single" && picked[0] ? "Tap to keep that spot in frame" : undefined}
          onClick={(e) => {
            if (kind !== "single" || !picked[0]) return
            const r = e.currentTarget.querySelector("img")?.getBoundingClientRect()
            if (!r) return
            setFocus([Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)), Math.min(1, Math.max(0, (e.clientY - r.top) / r.height))])
          }}>
          {/* eslint-disable-next-line @next/next/no-img-element -- a generated preview blob */}
          {preview.url ? <img src={preview.url} alt="Preview of your post" data-testid="studio-preview-img" /> : <div style={{ aspectRatio: "4 / 5", width: "100%" }} />}
          {preview.busy && <span className="h-preview-spin" aria-hidden />}
        </div>
        {kind === "carousel" && slides.length > 0 && (
          <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 10 }}>
            <button className="h-btn-ghost" aria-label="Previous slide" disabled={previewSlide === 0} onClick={() => setPreviewSlide((i) => i - 1)}><i className="ti ti-chevron-left" /></button>
            <span className="h-muted" style={{ fontSize: 13 }}>Slide {Math.min(previewSlide, slides.length) + 1} of {slides.length + 1}</span>
            <button className="h-btn-ghost" aria-label="Next slide" disabled={previewSlide >= slides.length} onClick={() => setPreviewSlide((i) => i + 1)}><i className="ti ti-chevron-right" /></button>
          </div>
        )}
        {preview.error && <span role="alert" style={{ color: "var(--err)", fontSize: 12 }}>{preview.error}</span>}
        {kind === "single" && picked[0] && <span className="h-muted" style={{ fontSize: 12, textAlign: "center" }}>Tap the picture to keep that spot in frame in every size</span>}
        <button className="h-btn-solid h-make-btn" disabled={!ready || making || (kind === "single" ? sizes.length === 0 : usable.length === 0)}
          onClick={() => void make()} data-testid="studio-make">
          <i className="ti ti-sparkles" /> {making ? "Making every size…" : kind === "carousel" ? `Make the carousel (${slides.length + 1} slides)` : `Make it — ${sizes.length} size${sizes.length === 1 ? "" : "s"}`}
        </button>
        {!ready && <span className="h-muted" style={{ fontSize: 12, textAlign: "center" }}>{photos.length ? why : "Add a photo to begin"}</span>}
        {refusal && (
          <div className="h-surface" data-testid="studio-refusal" style={{ padding: 10, borderRadius: 10, fontSize: 13, display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            <span style={{ flex: 1 }}>{refusal.detail}</span>
            {refusal.planNeeded && <Link href={`/billing?upgrade=${refusal.planNeeded}`} className="h-btn-solid" style={{ textDecoration: "none" }}>See plans</Link>}
          </div>
        )}
      </aside>

      {made && (
        <div className="h-sheet" role="dialog" aria-modal="true" aria-label="Your post is ready" onClick={(e) => { if (e.target === e.currentTarget) setMade(null) }}>
          <div className="h-sheet-body">
            <div style={{ display: "flex", alignItems: "center", marginBottom: 12 }}>
              <h2 className="h-display" style={{ fontSize: 22, margin: 0, flex: 1 }}>Your {made.kind === "carousel" ? "carousel" : "post"} is ready ✨</h2>
              <button className="h-btn-ghost" aria-label="Close" onClick={() => setMade(null)} data-testid="result-close"><i className="ti ti-x" /></button>
            </div>
            <PostResult post={made} onChange={onMade} />
          </div>
        </div>
      )}
    </div>
  )
}
