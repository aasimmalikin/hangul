/**
 * Brand Studio, client side: types, the size and layout lists (mirroring
 * backend `harness/brands/finish.py`), and the calls the studio makes.
 */

export type BrandColor = { role: string; hex: string }
export type HashtagSet = { name: string; tags: string[] }
export type Brand = {
  id: number; name: string; kind: string; look: string; colors: BrandColor[]; style: string; voice: string; font: string
  logo: string; logo_dark: string; handle: string; website: string; cta: string; footer: string; hashtags: HashtagSet[]
  paused: boolean; updated_at?: string | null; posts?: number; cover?: string | null
}
export type Listing = { brands: Brand[]; slots: number; used: number; can_add: boolean }
export type Asset = { id: number; brand_id: number; name: string; width: number; height: number; created_at: string | null }
export type PostFile = { name: string; size: string; width: number; height: number; label: string; slide?: number }
export type Caption = { label: string; text: string; hashtags: string[]; first_comment: string }
export type Slide = { image: string; headline: string; subline: string; price?: string }
export type Post = {
  id: number; brand_id: number; kind: "single" | "carousel"; layout: string; words: Record<string, string>; slides: Slide[]
  sizes: string[]; files: PostFile[]; captions: Record<string, Caption>
  review_status: "none" | "waiting" | "approved" | "changes"; review_comment: string; reviewed_at: string | null; created_at: string | null
}
export type Look = { id: string; label: string; colors: BrandColor[]; style: string; voice: string; font: string }
export type Suggestion = { kind: string; label: string; name: string; looks: Look[] }

export type WordKey = "headline" | "subline" | "price" | "cta"

/** backend finish.SIZES, with a short name and the ratio drawn on the chip */
export const SIZES: { key: string; name: string; label: string; w: number; h: number }[] = [
  { key: "post", name: "Square", label: "Instagram post 1:1", w: 1080, h: 1080 },
  { key: "portrait", name: "Feed 4:5", label: "Instagram feed 4:5", w: 1080, h: 1350 },
  { key: "story", name: "Story", label: "Story · Reel cover · WhatsApp status", w: 1080, h: 1920 },
  { key: "landscape", name: "Facebook", label: "Facebook · LinkedIn", w: 1200, h: 628 },
  { key: "x", name: "X", label: "X (Twitter)", w: 1600, h: 900 },
  { key: "youtube", name: "YouTube", label: "YouTube thumbnail", w: 1280, h: 720 },
  { key: "pinterest", name: "Pinterest", label: "Pinterest pin", w: 1000, h: 1500 },
  { key: "a4", name: "A4 print", label: "A4 print", w: 2480, h: 3508 },
]
export const CAROUSEL_SIZES = ["post", "portrait"]

/** backend finish.LAYOUTS: label, what it's for, the words it uses, and an icon */
export const LAYOUTS: { key: string; label: string; hint: string; words: WordKey[]; icon: string }[] = [
  { key: "band", label: "Classic", hint: "Your words on a colour band", words: ["headline", "subline", "price", "cta"], icon: "layout-bottombar" },
  { key: "offer", label: "Offer", hint: "A big badge for a price or sale", words: ["price", "headline", "subline", "cta"], icon: "discount-2" },
  { key: "event", label: "Event", hint: "Name, date and place over the photo", words: ["headline", "subline", "price", "cta"], icon: "calendar-event" },
  { key: "showcase", label: "Product", hint: "Your product framed on your colours", words: ["headline", "price", "subline", "cta"], icon: "shopping-bag" },
  { key: "quote", label: "Review", hint: "A customer's words, centre stage", words: ["headline", "subline"], icon: "quote" },
  { key: "top_banner", label: "Top banner", hint: "Headline across the top", words: ["headline", "subline", "price", "cta"], icon: "layout-navbar" },
  { key: "split", label: "Before / after", hint: "Two photos side by side", words: ["headline", "subline"], icon: "columns-2" },
  { key: "minimal", label: "Minimal", hint: "Just your photo, logo and handle", words: ["headline"], icon: "photo" },
]

/** What each word box is called, per layout where it reads differently. */
export function wordLabel(layout: string, key: WordKey): { label: string; placeholder: string } {
  const base: Record<WordKey, { label: string; placeholder: string }> = {
    headline: { label: "Headline", placeholder: "Kashmiri Kahwa · Today only" },
    subline: { label: "Details", placeholder: "Lal Chowk, Srinagar · 8 am to 9 pm" },
    price: { label: "Price or offer", placeholder: "₹80" },
    cta: { label: "Button text", placeholder: "Order now" },
  }
  if (layout === "quote") return key === "headline" ? { label: "What they said", placeholder: "The best kahwa outside my grandmother's kitchen!" }
    : { label: "Who said it", placeholder: "Priya, regular since 2021" }
  if (layout === "event") return key === "subline" ? { label: "Date and place", placeholder: "Sat 12 Oct · 7 pm · Lal Chowk" }
    : key === "headline" ? { label: "Event name", placeholder: "Sufi Night at Chinar" } : base[key]
  if (layout === "offer" && key === "price") return { label: "The offer", placeholder: "20% OFF" }
  if (layout === "minimal") return { label: "A short line (optional)", placeholder: "Good morning ☀️" }
  return base[key]
}

export const PLATFORMS: { key: string; label: string; icon: string; limit: number }[] = [
  { key: "instagram", label: "Instagram", icon: "brand-instagram", limit: 2200 },
  { key: "facebook", label: "Facebook", icon: "brand-facebook", limit: 2000 },
  { key: "linkedin", label: "LinkedIn", icon: "brand-linkedin", limit: 3000 },
  { key: "x", label: "X", icon: "brand-x", limit: 280 },
  { key: "whatsapp", label: "WhatsApp", icon: "brand-whatsapp", limit: 700 },
]

export const FONT_STACK: Record<string, string> = {
  sans: "system-ui, -apple-system, 'Segoe UI', sans-serif",
  serif: "Georgia, 'Times New Roman', serif",
  script: "'Brush Script MT', 'Segoe Script', cursive",
  display: "Impact, 'Arial Black', 'Helvetica Neue', sans-serif",
}
export const FONT_NAMES: Record<string, string> = { sans: "Modern", serif: "Elegant", script: "Handwritten", display: "Bold" }

export const colorOf = (colors: BrandColor[], role: string, fallback = "#222222") =>
  colors.find((c) => c.role === role)?.hex ?? fallback

export const fileUrl = (name: string, v?: string | null) => `/api/files/${encodeURIComponent(name)}${v ? `?v=${encodeURIComponent(v)}` : ""}`

/** Tells open pages (the chat's brand chip, /brands) that brands changed. */
export const BRAND_SAVED_EVENT = "hangul:brand-saved"

export type Refusal = { detail: string; code?: string; planNeeded?: string | null; buy?: string | null }

export async function json<T>(res: Response | null): Promise<T | Refusal> {
  if (!res) return { detail: "Hangul is unreachable right now. Try again in a moment." }
  const body = await res.json().catch(() => null)
  if (res.ok) return body as T
  return { detail: body?.detail ?? "Something went wrong. Try again in a moment.", code: body?.code, planNeeded: body?.planNeeded, buy: body?.buy }
}
export const isRefusal = (v: unknown): v is Refusal => Boolean(v && typeof v === "object" && "detail" in (v as object) && !("id" in (v as object)))

const send = (url: string, method: string, body?: unknown) =>
  fetch(url, { method, headers: body === undefined ? undefined : { "Content-Type": "application/json" },
               body: body === undefined ? undefined : JSON.stringify(body) }).catch(() => null)

export const api = {
  brands: () => fetch("/api/brands", { cache: "no-store" }).catch(() => null).then((r) => json<Listing>(r)),
  suggest: (sentence: string) => send("/api/brands/suggest", "POST", { sentence }).then((r) => json<Suggestion>(r)),
  create: (body: Partial<Brand> & { look?: string }) => send("/api/brands", "POST", body).then((r) => json<Brand>(r)),
  patch: (id: number, body: Partial<Brand>) => send(`/api/brands/${id}`, "PATCH", body).then((r) => json<Brand>(r)),
  remove: (id: number) => send(`/api/brands/${id}`, "DELETE"),
  logo: (id: number, file: File, dark = false) => {
    const form = new FormData()
    form.append("file", file)
    return fetch(`/api/brands/${id}/logo${dark ? "?variant=dark" : ""}`, { method: "POST", body: form }).catch(() => null)
      .then((r) => json<{ brand: Brand | null; suggested_colors: BrandColor[] }>(r))
  },
  assets: (id: number) => fetch(`/api/brands/${id}/assets`, { cache: "no-store" }).catch(() => null).then((r) => json<Asset[]>(r)),
  upload: (id: number, file: File) => {
    const form = new FormData()
    form.append("file", file)
    return fetch(`/api/brands/${id}/assets`, { method: "POST", body: form }).catch(() => null).then((r) => json<Asset>(r))
  },
  removeAsset: (id: number, aid: number) => send(`/api/brands/${id}/assets/${aid}`, "DELETE"),
  posts: (id: number) => fetch(`/api/brands/${id}/posts`, { cache: "no-store" }).catch(() => null).then((r) => json<Post[]>(r)),
  make: (id: number, design: unknown) => send(`/api/brands/${id}/posts`, "POST", design).then((r) => json<Post>(r)),
  removePost: (pid: number) => send(`/api/posts/${pid}`, "DELETE"),
  captions: (pid: number, platforms: string[], note = "") => send(`/api/posts/${pid}/captions`, "POST", { platforms, note }).then((r) => json<Post>(r)),
  editCaption: (pid: number, platform: string, c: Caption) =>
    send(`/api/posts/${pid}/captions`, "PATCH", { platform, text: c.text, hashtags: c.hashtags, first_comment: c.first_comment }).then((r) => json<Post>(r)),
  reviewLink: (pid: number) => send(`/api/posts/${pid}/review-link`, "POST").then((r) => json<{ url: string; token: string; expires_at: string }>(r)),
}

export function announceBrands(brand?: Brand) {
  if (typeof window !== "undefined") window.dispatchEvent(new CustomEvent(BRAND_SAVED_EVENT, { detail: brand ?? null }))
}
