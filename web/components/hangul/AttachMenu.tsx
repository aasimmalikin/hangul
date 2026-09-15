"use client"

import { useEffect, useRef, useState } from "react"
import { useSession } from "next-auth/react"

/** A document the backend indexed for this user. */
export type Attachment = { name: string; chunks: number }

const ACCEPT = ".pdf,.txt,.md"

/**
 * The `+` at the left of every composer. Opens a small menu of things to add
 * (just "Docs" for now); picking one opens the file chooser and the file is
 * sent to `/api/upload`, which indexes it for the signed-in user so
 * `search_docs` can find it on the next question.
 *
 * Signed-out users never reach the file chooser: `onRequireSignIn` fires with
 * the reason to show in the page's SignInModal.
 */
export function AttachMenu({
  onUploaded,
  onUploadingChange,
  onError,
  onRequireSignIn,
  placement = "above",
}: {
  /** Where the menu opens relative to the button. */
  placement?: "above" | "below"
  onUploaded: (a: Attachment) => void
  onUploadingChange?: (name: string | null) => void
  onError?: (message: string | null) => void
  onRequireSignIn: (reason: string) => void
}) {
  const { status } = useSession()
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (!open) return
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener("mousedown", onDoc)
    return () => document.removeEventListener("mousedown", onDoc)
  }, [open])

  const onPlus = () => {
    if (status !== "authenticated") {
      onRequireSignIn("Sign in to add a document and ask questions about it.")
      return
    }
    setOpen((o) => !o)
  }

  const pickDocs = () => {
    setOpen(false)
    fileRef.current?.click()
  }

  const upload = async (file: File) => {
    setBusy(true)
    onUploadingChange?.(file.name)
    onError?.(null)
    try {
      const form = new FormData()
      form.append("file", file)
      const res = await fetch("/api/upload", { method: "POST", body: form, signal: AbortSignal.timeout(120_000) })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        if (res.status === 401) {
          onRequireSignIn("Your session has expired. Sign in again to add the document.")
          return
        }
        onError?.(typeof data.detail === "string" ? data.detail : `Upload failed (${res.status})`)
        return
      }
      onUploaded({ name: data.filename ?? file.name, chunks: data.chunks_indexed ?? 0 })
    } catch (e) {
      onError?.((e as Error)?.name === "TimeoutError"
        ? "The upload timed out. Try a smaller file."
        : "Upload failed. Check your connection and try again.")
    } finally {
      setBusy(false)
      onUploadingChange?.(null)
      if (fileRef.current) fileRef.current.value = ""
    }
  }

  return (
    <div ref={ref} style={{ position: "relative", flexShrink: 0 }}>
      <input
        ref={fileRef}
        type="file"
        accept={ACCEPT}
        hidden
        onChange={(e) => { const f = e.target.files?.[0]; if (f) upload(f) }}
      />
      <button
        type="button"
        className="h-icon-btn"
        style={{ borderRadius: "50%" }}
        onClick={onPlus}
        disabled={busy}
        aria-label="Add"
        aria-haspopup="menu"
        aria-expanded={open}
        title="Add"
      >
        <i className={`ti ${busy ? "ti-loader-2 animate-spin" : "ti-plus"}`} style={{ fontSize: 16 }} />
      </button>

      {open && (
        <div className="h-popover" role="menu" style={{ position: "absolute", ...(placement === "above" ? { bottom: 40 } : { top: 40 }), left: 0, minWidth: 140, zIndex: 30 }}>
          <button
            role="menuitem"
            className="h-btn-ghost"
            style={{ width: "100%", justifyContent: "flex-start", padding: "8px 10px", gap: 10 }}
            onClick={pickDocs}
          >
            <i className="ti ti-file-text" style={{ fontSize: 15 }} />
            Docs
          </button>
        </div>
      )}
    </div>
  )
}
