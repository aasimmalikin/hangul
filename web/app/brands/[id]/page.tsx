"use client"

import Link from "next/link"
import { use, useCallback, useEffect, useState } from "react"
import { useRouter, useSearchParams } from "next/navigation"
import { useSession } from "next-auth/react"
import { AppHeader } from "@/components/hangul/AppHeader"
import { SignInModal, type AuthMode } from "@/components/hangul/SignInModal"
import { Swatches } from "@/components/hangul/BrandSetup"
import { BrandStudio } from "@/components/hangul/BrandStudio"
import { BrandKit } from "@/components/hangul/BrandKit"
import { PhotoDrop, PhotoGrid } from "@/components/hangul/BrandPhotos"
import { PostResult } from "@/components/hangul/PostResult"
import { api, fileUrl, FONT_STACK, isRefusal, LAYOUTS, type Asset, type Brand, type Post } from "@/lib/brands"

/**
 * One brand's studio: Create (photo -> layout -> words -> sizes, live preview),
 * Posts (everything made for it, with captions, ZIP and client review), Photos
 * (the library) and Kit (logos, colours, font, voice, handle, hashtags).
 */
type Tab = "create" | "posts" | "photos" | "kit"
const TABS: { key: Tab; label: string; icon: string }[] = [
  { key: "create", label: "Create", icon: "wand" },
  { key: "posts", label: "Posts", icon: "layout-grid" },
  { key: "photos", label: "Photos", icon: "photo" },
  { key: "kit", label: "Brand kit", icon: "palette" },
]

function StatusBadge({ p }: { p: Post }) {
  if (p.review_status === "approved") return <span className="h-badge" data-tone="ok"><i className="ti ti-check" /> Approved</span>
  if (p.review_status === "changes") return <span className="h-badge" data-tone="warn">Changes asked</span>
  if (p.review_status === "waiting") return <span className="h-badge">With client</span>
  return null
}

export default function BrandPage({ params }: { params: Promise<{ id: string }> }) {
  const { id: raw } = use(params)
  const id = Number(raw)
  const { status } = useSession()
  const router = useRouter()
  const search = useSearchParams()
  const [signIn, setSignIn] = useState<{ open: boolean; mode: AuthMode }>({ open: false, mode: "signin" })
  const [dismissed, setDismissed] = useState(false)
  const [brands, setBrands] = useState<Brand[] | null>(null)
  const [photos, setPhotos] = useState<Asset[]>([])
  const [posts, setPosts] = useState<Post[]>([])
  const [error, setError] = useState<string | null>(null)
  const tab = (TABS.some((t) => t.key === search.get("tab")) ? search.get("tab") : "create") as Tab
  const openPost = Number(search.get("post") ?? 0)
  const brand = brands?.find((b) => b.id === id) ?? null

  const go = useCallback((q: Record<string, string | null>) => {
    const next = new URLSearchParams(search.toString())
    for (const [k, v] of Object.entries(q)) { if (v === null) next.delete(k); else next.set(k, v) }
    router.replace(`/brands/${id}${next.size ? `?${next}` : ""}`, { scroll: false })
  }, [router, search, id])

  const load = useCallback(async () => {
    const [b, a, p] = await Promise.all([api.brands(), api.assets(id), api.posts(id)])
    if (isRefusal(b)) { setError("Couldn't load this brand right now."); return }
    setBrands(b.brands)
    if (!b.brands.some((x) => x.id === id)) { setError("This brand doesn't exist, or it was removed."); return }
    if (!isRefusal(a)) setPhotos(a)
    if (!isRefusal(p)) setPosts(p)
  }, [id])

  useEffect(() => {
    if (status !== "authenticated") return
    // Fetch-on-sign-in; state is set after the awaits.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load()
  }, [status, load])

  const removePhoto = async (a: Asset) => {
    const res = await api.removeAsset(id, a.id)
    if (res?.ok) setPhotos((ps) => ps.filter((x) => x.id !== a.id))
  }
  const removePost = async (p: Post) => {
    const res = await api.removePost(p.id)
    if (res?.ok) { setPosts((ps) => ps.filter((x) => x.id !== p.id)); go({ post: null }) }
  }
  const upsertPost = (p: Post) => setPosts((ps) => [p, ...ps.filter((x) => x.id !== p.id)])
  const shown = posts.find((p) => p.id === openPost)

  return (
    <main className="h-has-bottom-nav" style={{ minHeight: "100vh", display: "flex", flexDirection: "column" }}>
      <AppHeader onSignIn={() => setSignIn({ open: true, mode: "signin" })} onSignUp={() => setSignIn({ open: true, mode: "signup" })} />
      <SignInModal open={signIn.open || (status === "unauthenticated" && !dismissed)} mode={signIn.mode}
        onClose={() => { setDismissed(true); setSignIn((s) => ({ ...s, open: false })) }} callbackUrl={`/brands/${id}`} reason="Sign in to open your Brand Studio." />
      <div className="h-studio-page">
        <div className="h-studio-head">
          <Link href="/brands" className="h-btn-ghost" aria-label="All brands" style={{ textDecoration: "none" }}><i className="ti ti-arrow-left" /></Link>
          {brand?.logo
            // eslint-disable-next-line @next/next/no-img-element -- the user's own logo
            ? <img src={fileUrl(brand.logo, brand.updated_at)} alt="" style={{ width: 40, height: 40, objectFit: "contain", borderRadius: 10, background: "var(--surface-hover)" }} />
            : null}
          <div style={{ minWidth: 0, flex: 1 }}>
            <h1 style={{ margin: 0, fontSize: 24, fontFamily: FONT_STACK[brand?.font ?? "serif"], overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} data-testid="studio-brand">
              {brand?.name ?? " "}
            </h1>
            {brand && <span style={{ display: "flex", gap: 8, alignItems: "center" }}><Swatches colors={brand.colors} size={12} />
              {brand.handle && <span className="h-muted" style={{ fontSize: 12 }}>@{brand.handle.replace(/^@+/, "")}</span>}</span>}
          </div>
          {brands && brands.length > 1 && (
            <select className="h-input" aria-label="Switch brand" value={id} style={{ width: "auto" }} data-testid="brand-switch"
              onChange={(e) => router.push(`/brands/${e.target.value}`)}>
              {brands.filter((b) => !b.paused).map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
            </select>
          )}
        </div>

        <div className="h-studio-tabs" role="tablist" aria-label="Brand studio">
          {TABS.map((t) => (
            <button key={t.key} role="tab" aria-selected={tab === t.key} data-testid={`tab-${t.key}`} onClick={() => go({ tab: t.key === "create" ? null : t.key, post: null })}>
              <i className={`ti ti-${t.icon}`} style={{ marginRight: 5 }} />{t.label}
              {t.key === "posts" && posts.length > 0 && <span className="h-muted" style={{ marginLeft: 5, fontSize: 12 }}>{posts.length}</span>}
            </button>
          ))}
        </div>

        {error && <div className="h-surface" role="alert" style={{ padding: 14, borderRadius: 12 }}>{error} <Link href="/brands">Back to your brands</Link></div>}
        {brand?.paused && (
          <div className="h-surface" style={{ padding: 14, borderRadius: 12 }}>
            This brand is paused because your plan includes fewer brands now. <Link href="/billing">Upgrade</Link> or remove another brand to use it again.
          </div>
        )}

        {brand && !brand.paused && tab === "create" && (
          <BrandStudio key={brand.id} brand={brand} photos={photos} onPhotosChange={setPhotos} onMade={upsertPost}
            prefill={Object.fromEntries(["layout", "headline", "subline", "price", "cta", "from"]
              .map((k) => [k, search.get(k) ?? undefined]).filter(([, v]) => v))} />
        )}

        {brand && tab === "posts" && (
          posts.length === 0
            ? <div className="h-studio-panel" style={{ alignItems: "flex-start" }}>
                <span>Nothing made for {brand.name} yet.</span>
                <button className="h-btn-solid" onClick={() => go({ tab: null })}><i className="ti ti-wand" /> Make your first post</button>
              </div>
            : <div className="h-post-grid" data-testid="post-library">
                {posts.map((p) => (
                  <button key={p.id} className="h-post-tile" onClick={() => go({ post: String(p.id) })} data-testid="post-tile">
                    {/* eslint-disable-next-line @next/next/no-img-element -- the user's own post */}
                    <img src={fileUrl(p.files.find((f) => f.size === "portrait")?.name ?? p.files[0]?.name ?? "")} alt="" loading="lazy" />
                    <span style={{ fontSize: 13, fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {p.words.headline || p.slides[0]?.headline || LAYOUTS.find((l) => l.key === p.layout)?.label}
                    </span>
                    <span style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
                      <span className="h-muted" style={{ fontSize: 12 }}>{p.created_at ? new Date(p.created_at).toLocaleDateString() : ""}{p.kind === "carousel" ? " · carousel" : ""}</span>
                      <StatusBadge p={p} />
                    </span>
                  </button>
                ))}
              </div>
        )}

        {brand && tab === "photos" && (
          <section className="h-studio-panel">
            <div className="h-studio-step"><i className="ti ti-photo" /> {brand.name}&apos;s photos</div>
            <span className="h-muted" style={{ fontSize: 13, marginTop: -6 }}>Upload product shots, your shop and your team once; use them in any post.</span>
            <PhotoDrop brandId={brand.id} onAdded={(a) => setPhotos((ps) => [a, ...ps])} />
            <PhotoGrid photos={photos} onRemove={(a) => void removePhoto(a)} />
          </section>
        )}

        {brand && tab === "kit" && <BrandKit key={brand.updated_at ?? brand.id} brand={brand} onSaved={(b) => setBrands((bs) => bs?.map((x) => (x.id === b.id ? { ...x, ...b } : x)) ?? null)} />}

        {shown && (
          <div className="h-sheet" role="dialog" aria-modal="true" aria-label="Post" onClick={(e) => { if (e.target === e.currentTarget) go({ post: null }) }}>
            <div className="h-sheet-body">
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
                <h2 className="h-display" style={{ fontSize: 20, margin: 0, flex: 1 }}>{shown.words.headline || shown.slides[0]?.headline || "Post"}</h2>
                <button className="h-btn-ghost" style={{ fontSize: 12, color: "var(--err)" }} onClick={() => void removePost(shown)} data-testid="post-delete"><i className="ti ti-trash" /> Remove</button>
                <button className="h-btn-ghost" aria-label="Close" onClick={() => go({ post: null })}><i className="ti ti-x" /></button>
              </div>
              <PostResult post={shown} onChange={upsertPost} />
            </div>
          </div>
        )}
      </div>
    </main>
  )
}
