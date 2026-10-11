"use client"

import { useRef, useState } from "react"
import { api, fileUrl, isRefusal, type Asset } from "@/lib/brands"

/**
 * The brand's photo library: drop (or pick, or shoot on a phone) several photos
 * at once; they upload one after another and land in the grid. In the studio
 * the grid picks photos (one, two for before/after, or many in order for a
 * carousel); on the Photos tab it manages them.
 */
export function PhotoDrop({ brandId, onAdded, compact = false }: { brandId: number; onAdded: (a: Asset) => void; compact?: boolean }) {
  const input = useRef<HTMLInputElement>(null)
  const [over, setOver] = useState(false)
  const [progress, setProgress] = useState<{ done: number; total: number } | null>(null)
  const [error, setError] = useState<string | null>(null)

  const upload = async (files: File[]) => {
    const photos = files.filter((f) => f.type.startsWith("image/") || /\.(jpe?g|png|webp|heic|heif)$/i.test(f.name)).slice(0, 30)
    if (!photos.length) { setError("Those don't look like photos. Try JPG, PNG or WebP."); return }
    setError(null)
    setProgress({ done: 0, total: photos.length })
    for (const [i, f] of photos.entries()) {
      const r = await api.upload(brandId, f)
      if (isRefusal(r)) setError(`${f.name}: ${r.detail}`)
      else onAdded(r)
      setProgress({ done: i + 1, total: photos.length })
    }
    setProgress(null)
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <input ref={input} type="file" accept="image/*" multiple hidden data-testid="photo-input"
        onChange={(e) => { const fs = Array.from(e.target.files ?? []); e.target.value = ""; void upload(fs) }} />
      <button type="button" className="h-drop" data-over={over} data-testid="photo-drop" disabled={progress !== null}
        style={compact ? { padding: 12, flexDirection: "row" } : undefined}
        onClick={() => input.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setOver(true) }} onDragLeave={() => setOver(false)}
        onDrop={(e) => { e.preventDefault(); setOver(false); void upload(Array.from(e.dataTransfer.files ?? [])) }}>
        <i className="ti ti-camera-plus" />
        {progress
          ? <span>Uploading {progress.done + 1 > progress.total ? progress.total : progress.done + 1} of {progress.total}…</span>
          : <span><b>Drop photos here</b> or tap to choose{compact ? "" : <> · take one with your phone · up to 30 at once</>}</span>}
      </button>
      {error && <span role="alert" style={{ color: "var(--err)", fontSize: 12 }}>{error}</span>}
    </div>
  )
}

export function PhotoGrid({ photos, selected = [], onPick, onRemove, numbered = false }: {
  photos: Asset[]; selected?: string[]; onPick?: (name: string) => void; onRemove?: (a: Asset) => void; numbered?: boolean
}) {
  if (!photos.length) return null
  return (
    <div className="h-photo-grid" data-testid="photo-grid">
      {photos.map((a) => {
        const at = selected.indexOf(a.name)
        return (
          <div key={a.id} className="h-photo" role={onPick ? "button" : undefined} tabIndex={onPick ? 0 : undefined}
            aria-pressed={onPick ? at >= 0 : undefined} data-testid="photo" title={a.name}
            onClick={() => onPick?.(a.name)} onKeyDown={(e) => { if (onPick && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); onPick(a.name) } }}>
            {/* eslint-disable-next-line @next/next/no-img-element -- the user's own photo behind the BFF */}
            <img src={fileUrl(a.name)} alt="" loading="lazy" />
            {at >= 0 && numbered && <span className="h-photo-num">{at + 1}</span>}
            {at >= 0 && !numbered && <span className="h-photo-num"><i className="ti ti-check" /></span>}
            {onRemove && (
              <button type="button" className="h-photo-del" aria-label={`Remove ${a.name}`} data-testid="photo-remove"
                onClick={(e) => { e.stopPropagation(); onRemove(a) }}>
                <i className="ti ti-x" style={{ fontSize: 14 }} />
              </button>
            )}
          </div>
        )
      })}
    </div>
  )
}
