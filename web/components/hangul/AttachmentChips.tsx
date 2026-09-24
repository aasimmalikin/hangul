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
          style={{ cursor: "default", display: "inline-flex", alignItems: "center", gap: 6,
                   ...(a.warning ? { borderColor: "var(--err)" } : {}) }}
          title={a.warning ?? (a.chunks ? `${a.chunks} chunks indexed` : undefined)}
          data-testid={a.warning ? "attachment-warning" : undefined}
        >
          <i className={`ti ${a.warning ? "ti-shield-exclamation" : "ti-file-text"}`} style={{ fontSize: 13, ...(a.warning ? { color: "var(--err)" } : {}) }} />
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
      {attachments.some((a) => a.warning) && (
        <span className="h-muted" style={{ fontSize: 12, alignSelf: "center", flexBasis: "100%" }} role="status">
          {attachments.filter((a) => a.warning).map((a) => a.warning).join(" ")} The assistant treats such passages as data, never as commands.
        </span>
      )}
    </div>
  )
}
