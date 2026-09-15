"use client"

import type { Attachment } from "@/components/hangul/AttachMenu"

/** The row of attached-document chips above a composer, plus upload status. */
export function AttachmentChips({
  attachments,
  uploading,
  error,
  style,
}: {
  attachments: Attachment[]
  uploading: string | null
  error: string | null
  style?: React.CSSProperties
}) {
  if (attachments.length === 0 && !uploading && !error) return null
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 6, ...style }}>
      {attachments.map((a, i) => (
        <span
          key={`${a.name}-${i}`}
          className="h-chip"
          style={{ cursor: "default", display: "inline-flex", alignItems: "center", gap: 6 }}
          title={a.chunks ? `${a.chunks} chunks indexed` : undefined}
        >
          <i className="ti ti-file-text" style={{ fontSize: 13 }} />
          {a.name}
        </span>
      ))}
      {uploading && (
        <span className="h-chip h-muted" style={{ cursor: "default", display: "inline-flex", alignItems: "center", gap: 6 }}>
          <i className="ti ti-loader-2 animate-spin" style={{ fontSize: 13 }} />
          Indexing {uploading}…
        </span>
      )}
      {error && <span style={{ fontSize: 12, color: "var(--err)", alignSelf: "center" }}>{error}</span>}
    </div>
  )
}
