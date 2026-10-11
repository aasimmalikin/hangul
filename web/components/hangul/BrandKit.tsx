"use client"

import { useRef, useState } from "react"
import { MiniPoster } from "@/components/hangul/BrandSetup"
import { announceBrands, api, fileUrl, FONT_NAMES, FONT_STACK, isRefusal, type Brand, type BrandColor, type HashtagSet } from "@/lib/brands"

/**
 * The brand kit, all in one place: logos (light and dark), colours, font,
 * the look and voice, @handle, website, button text, a footer line and
 * hashtag sets. An agency fills it in once per client.
 */
const ROLE_NAMES: Record<string, string> = { primary: "Main", secondary: "Background", accent: "Highlight", text: "Text" }

function LogoSlot({ brand, dark, onSaved }: { brand: Brand; dark: boolean; onSaved: (b: Brand) => void }) {
  const ref = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const name = dark ? brand.logo_dark : brand.logo
  const up = async (f: File) => {
    setBusy(true); setError(null)
    const r = await api.logo(brand.id, f, dark)
    setBusy(false)
    if (isRefusal(r)) setError(r.detail)
    else if (r.brand) onSaved(r.brand)
  }
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6, alignItems: "flex-start" }}>
      <input ref={ref} type="file" accept=".png,.jpg,.jpeg,.webp" hidden onChange={(e) => { const f = e.target.files?.[0]; if (f) void up(f); e.target.value = "" }} />
      <button type="button" className="h-drop" style={{ width: 150, height: 110, padding: 8, background: dark ? "var(--solid-bg)" : undefined }}
        onClick={() => ref.current?.click()} disabled={busy} data-testid={dark ? "kit-logo-dark" : "kit-logo"}>
        {name
          // eslint-disable-next-line @next/next/no-img-element -- the user's own logo
          ? <img src={fileUrl(name, brand.updated_at)} alt="" style={{ maxWidth: "100%", maxHeight: 70, objectFit: "contain" }} />
          : <i className="ti ti-photo-up" />}
        <span style={{ fontSize: 12, color: dark ? "var(--solid-fg)" : undefined }}>{busy ? "Uploading…" : name ? "Change" : "Upload"}</span>
      </button>
      <span className="h-muted" style={{ fontSize: 12 }}>{dark ? "For dark backgrounds (optional)" : "Main logo"}</span>
      {error && <span style={{ color: "var(--err)", fontSize: 12 }}>{error}</span>}
    </div>
  )
}

export function BrandKit({ brand, onSaved }: { brand: Brand; onSaved: (b: Brand) => void }) {
  const [b, setB] = useState(brand)
  const [tagsText, setTagsText] = useState<string[]>((brand.hashtags ?? []).map((s) => s.tags.join(" ")))
  const [sets, setSets] = useState<HashtagSet[]>(brand.hashtags ?? [])
  const [busy, setBusy] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const set = <K extends keyof Brand>(k: K, v: Brand[K]) => { setB((x) => ({ ...x, [k]: v })); setSaved(false) }

  const save = async () => {
    setBusy(true); setError(null)
    const hashtags = sets.map((s, i) => ({ name: s.name || `Set ${i + 1}`, tags: (tagsText[i] ?? "").split(/[\s,]+/).filter(Boolean) }))
      .filter((s) => s.tags.length)
    const r = await api.patch(b.id, { name: b.name, colors: b.colors, font: b.font, style: b.style, voice: b.voice, handle: b.handle,
                                      website: b.website, cta: b.cta, footer: b.footer, hashtags })
    setBusy(false)
    if (isRefusal(r)) { setError(r.detail); return }
    setB(r); setSets(r.hashtags); setTagsText(r.hashtags.map((s) => s.tags.join(" ")))
    setSaved(true)
    onSaved(r)
    announceBrands(r)
  }

  const logoSaved = (nb: Brand) => { setB((x) => ({ ...x, logo: nb.logo, logo_dark: nb.logo_dark, updated_at: nb.updated_at })); onSaved(nb) }

  return (
    <div className="h-studio-grid">
      <div style={{ display: "flex", flexDirection: "column", gap: 14, minWidth: 0 }}>
        <section className="h-studio-panel">
          <div className="h-studio-step"><i className="ti ti-badge" /> Name and logos</div>
          <label className="h-field"><span>Brand name</span>
            <input className="h-input" value={b.name} maxLength={80} onChange={(e) => set("name", e.target.value)} data-testid="kit-name" />
          </label>
          <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
            <LogoSlot brand={b} dark={false} onSaved={logoSaved} />
            <LogoSlot brand={b} dark onSaved={logoSaved} />
          </div>
        </section>

        <section className="h-studio-panel">
          <div className="h-studio-step"><i className="ti ti-palette" /> Colours and font</div>
          <div className="h-kit-colors">
            {b.colors.map((c: BrandColor, i) => (
              <label key={c.role} className="h-kit-color">
                <input type="color" value={c.hex} aria-label={`${ROLE_NAMES[c.role] ?? c.role} colour`}
                  onChange={(e) => set("colors", b.colors.map((x, j) => (j === i ? { ...x, hex: e.target.value.toUpperCase() } : x)))} />
                {ROLE_NAMES[c.role] ?? c.role}
              </label>
            ))}
          </div>
          <div className="h-size-row" role="group" aria-label="Font">
            {Object.keys(FONT_STACK).map((f) => (
              <button key={f} className="h-size-chip" aria-pressed={b.font === f} onClick={() => set("font", f)} style={{ fontFamily: FONT_STACK[f], fontSize: 15 }}>
                {FONT_NAMES[f]}
              </button>
            ))}
          </div>
        </section>

        <section className="h-studio-panel">
          <div className="h-studio-step"><i className="ti ti-message-heart" /> Look and voice</div>
          <label className="h-field"><span>How your photos should feel</span>
            <textarea className="h-input" rows={2} maxLength={300} value={b.style} onChange={(e) => set("style", e.target.value)} placeholder="warm natural light, wooden textures, cosy" />
            <small>Used when Hangul improves a photo or draws a new one.</small>
          </label>
          <label className="h-field"><span>How you sound</span>
            <input className="h-input" maxLength={300} value={b.voice} onChange={(e) => set("voice", e.target.value)} placeholder="friendly and playful, short sentences" />
            <small>Used for captions.</small>
          </label>
        </section>

        <section className="h-studio-panel">
          <div className="h-studio-step"><i className="ti ti-world" /> On every post</div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 10 }}>
            <label className="h-field"><span>Instagram handle</span>
              <input className="h-input" value={b.handle} maxLength={60} onChange={(e) => set("handle", e.target.value)} placeholder="@chinarcafe" data-testid="kit-handle" />
            </label>
            <label className="h-field"><span>Website or order link</span>
              <input className="h-input" value={b.website} maxLength={200} onChange={(e) => set("website", e.target.value)} placeholder="chinarcafe.in" />
            </label>
            <label className="h-field"><span>Usual button text</span>
              <input className="h-input" value={b.cta} maxLength={60} onChange={(e) => set("cta", e.target.value)} placeholder="Order on Zomato" />
            </label>
            <label className="h-field"><span>Footer line</span>
              <input className="h-input" value={b.footer} maxLength={120} onChange={(e) => set("footer", e.target.value)} placeholder="Lal Chowk · 98765 43210" />
            </label>
          </div>
        </section>

        <section className="h-studio-panel">
          <div className="h-studio-step"><i className="ti ti-hash" /> Hashtag sets</div>
          <span className="h-muted" style={{ fontSize: 12.5, marginTop: -6 }}>Captions always start with these. Keep a set per occasion.</span>
          {sets.map((s, i) => (
            <div key={i} style={{ display: "grid", gridTemplateColumns: "minmax(100px, 160px) 1fr auto", gap: 8, alignItems: "start" }}>
              <input className="h-input" value={s.name} maxLength={40} placeholder="Everyday" aria-label="Set name"
                onChange={(e) => { setSets((xs) => xs.map((x, j) => (j === i ? { ...x, name: e.target.value } : x))); setSaved(false) }} />
              <input className="h-input" value={tagsText[i] ?? ""} placeholder="#srinagar #kahwa #chinarcafe" aria-label="Hashtags" data-testid="kit-tags"
                onChange={(e) => { setTagsText((xs) => xs.map((x, j) => (j === i ? e.target.value : x))); setSaved(false) }} />
              <button className="h-btn-ghost" aria-label="Remove set" onClick={() => { setSets((xs) => xs.filter((_, j) => j !== i)); setTagsText((xs) => xs.filter((_, j) => j !== i)); setSaved(false) }}>
                <i className="ti ti-x" />
              </button>
            </div>
          ))}
          {sets.length < 10 && (
            <button className="h-btn-ghost" style={{ alignSelf: "flex-start", gap: 6 }} data-testid="kit-add-tags"
              onClick={() => { setSets((xs) => [...xs, { name: xs.length ? "" : "Everyday", tags: [] }]); setTagsText((xs) => [...xs, ""]) }}>
              <i className="ti ti-plus" /> Add a hashtag set
            </button>
          )}
        </section>
      </div>

      <aside className="h-preview">
        <MiniPoster name={b.name} colors={b.colors} font={b.font} logo={b.logo || undefined} logoVersion={b.updated_at} />
        {(b.handle || b.website) && <span className="h-muted" style={{ fontSize: 12, textAlign: "center" }}>{[b.handle && `@${b.handle.replace(/^@/, "")}`, b.website].filter(Boolean).join(" · ")}</span>}
        <button className="h-btn-solid h-make-btn" onClick={() => void save()} disabled={busy} data-testid="kit-save">
          <i className={`ti ti-${saved ? "check" : "device-floppy"}`} /> {busy ? "Saving…" : saved ? "Saved" : "Save brand kit"}
        </button>
        {error && <span role="alert" style={{ color: "var(--err)", fontSize: 12 }}>{error}</span>}
      </aside>
    </div>
  )
}
