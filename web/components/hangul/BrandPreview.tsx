"use client"

import { useEffect, useRef, useState } from "react"

/**
 * The live preview: POST the design to /api/brands/<id>/preview (a small JPEG
 * rendered by the same code that makes the real post, free) and show it. Requests
 * are debounced and stale answers dropped, so typing never flickers backwards.
 */
export function useDesignPreview(brandId: number | null, design: unknown, delayMs = 300) {
  const [url, setUrl] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const seq = useRef(0)
  const key = JSON.stringify(design)

  useEffect(() => {
    if (brandId === null) return
    const mine = ++seq.current
    const ctrl = new AbortController()
    const t = setTimeout(async () => {
      setBusy(true)
      try {
        const res = await fetch(`/api/brands/${brandId}/preview`, { method: "POST", headers: { "Content-Type": "application/json" }, body: key, signal: ctrl.signal })
        if (mine !== seq.current) return
        if (!res.ok) {
          const j = await res.json().catch(() => null)
          setError(j?.detail ?? "The preview isn't available right now.")
          return
        }
        const blob = await res.blob()
        if (mine !== seq.current) return
        setError(null)
        setUrl((old) => { if (old) URL.revokeObjectURL(old); return URL.createObjectURL(blob) })
      } catch { /* aborted or offline: keep the last preview */ } finally {
        if (mine === seq.current) setBusy(false)
      }
    }, delayMs)
    return () => { clearTimeout(t); ctrl.abort() }
  }, [brandId, key, delayMs])

  useEffect(() => () => { if (url) URL.revokeObjectURL(url) }, [url])
  return { url, busy, error }
}

/** A brand's sample post (its cover before it has any posts). */
export function BrandSample({ brandId, name, version }: { brandId: number; name: string; version?: string | null }) {
  const { url } = useDesignPreview(brandId, { layout: "band", size: "portrait", words: { headline: "Today's special", subline: name }, v: version }, 0)
  // eslint-disable-next-line @next/next/no-img-element -- a generated preview blob
  return url ? <img src={url} alt="" /> : <span style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center" }} className="h-muted"><i className="ti ti-photo" /></span>
}
