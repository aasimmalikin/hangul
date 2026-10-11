"use client"

import Link from "next/link"
import { useMemo, useState } from "react"
import { api, fileUrl, isRefusal, PLATFORMS, SIZES, type Caption, type Post, type Refusal } from "@/lib/brands"

/**
 * A finished post: every size (and every carousel slide) to flip through and
 * download, the whole set as a ZIP, captions per platform in the brand's voice
 * (editable, with copy buttons and the platform's limit), and a private link to
 * send to the client for approval.
 */
function Upgrade({ r }: { r: Refusal }) {
  return (
    <div className="h-surface" style={{ padding: 10, borderRadius: 10, fontSize: 13, display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
      <span style={{ flex: 1 }}>{r.detail}</span>
      {r.planNeeded && <Link href={`/billing?upgrade=${r.planNeeded}`} className="h-btn-solid" style={{ textDecoration: "none", fontSize: 13 }}>See plans</Link>}
    </div>
  )
}

function CaptionBox({ post, platform, c, onSaved }: { post: Post; platform: string; c: Caption; onSaved: (p: Post) => void }) {
  const meta = PLATFORMS.find((p) => p.key === platform)
  const [text, setText] = useState(c.text)
  const [copied, setCopied] = useState(false)
  const tags = c.hashtags.join(" ")
  const length = text.length + (platform === "x" && tags ? tags.length + 1 : 0)
  const full = platform === "instagram" || !tags ? text : `${text}\n\n${tags}`
  const copy = async () => {
    try { await navigator.clipboard.writeText(full); setCopied(true); setTimeout(() => setCopied(false), 1500) } catch { /* no clipboard */ }
  }
  const save = async () => {
    if (text === c.text) return
    const r = await api.editCaption(post.id, platform, { ...c, text })
    if (!isRefusal(r)) onSaved(r)
  }
  return (
    <div className="h-caption" data-testid={`caption-${platform}`}>
      <div className="h-caption-head">
        <i className={`ti ti-${meta?.icon ?? "message"}`} /> {c.label || meta?.label}
        <span className="h-caption-count" data-over={meta ? length > meta.limit : false}>{length}/{meta?.limit}</span>
      </div>
      <textarea className="h-input" value={text} onChange={(e) => setText(e.target.value)} onBlur={() => void save()} aria-label={`${meta?.label} caption`} />
      {tags && <span style={{ fontSize: 12, color: "var(--link)" }}>{tags}</span>}
      {c.first_comment && platform === "instagram" && <span className="h-muted" style={{ fontSize: 12 }}>First comment: {c.first_comment}</span>}
      <button className="h-btn-ghost" style={{ alignSelf: "flex-start", fontSize: 12, gap: 4 }} onClick={() => void copy()}>
        <i className={`ti ti-${copied ? "check" : "copy"}`} /> {copied ? "Copied" : "Copy"}
      </button>
    </div>
  )
}

export function PostResult({ post: initial, onChange }: { post: Post; onChange?: (p: Post) => void }) {
  const [post, setPost] = useState(initial)
  const update = (p: Post) => { setPost(p); onChange?.(p) }
  const sizes = useMemo(() => Array.from(new Set(post.files.map((f) => f.size))), [post.files])
  const [size, setSize] = useState(sizes[0])
  const shown = post.files.filter((f) => f.size === size)
  const [slide, setSlide] = useState(0)
  const file = shown[Math.min(slide, shown.length - 1)]
  const [platforms, setPlatforms] = useState<string[]>(Object.keys(post.captions).length ? Object.keys(post.captions) : ["instagram", "facebook", "whatsapp"])
  const [writing, setWriting] = useState(false)
  const [note, setNote] = useState("")
  const [refusal, setRefusal] = useState<Refusal | null>(null)
  const [link, setLink] = useState<{ url: string; expires_at: string } | null>(null)
  const [linkBusy, setLinkBusy] = useState(false)
  const [copied, setCopied] = useState(false)

  const write = async () => {
    setWriting(true); setRefusal(null)
    const r = await api.captions(post.id, platforms, note)
    setWriting(false)
    if (isRefusal(r)) setRefusal(r)
    else update(r)
  }
  const share = async () => {
    setLinkBusy(true); setRefusal(null)
    const r = await api.reviewLink(post.id)
    setLinkBusy(false)
    if (isRefusal(r)) { setRefusal(r); return }
    setLink(r)
    update({ ...post, review_status: "waiting", review_comment: "" })
  }
  const copyLink = async () => {
    if (!link) return
    try { await navigator.clipboard.writeText(link.url); setCopied(true); setTimeout(() => setCopied(false), 1500) } catch { /* no clipboard */ }
  }
  const status = post.review_status

  return (
    <div className="h-result" data-testid="post-result">
      {sizes.length > 1 && (
        <div className="h-studio-tabs" role="tablist" aria-label="Sizes">
          {sizes.map((s) => (
            <button key={s} role="tab" aria-selected={s === size} data-testid="result-size" onClick={() => { setSize(s); setSlide(0) }}>
              {SIZES.find((x) => x.key === s)?.name ?? s}
            </button>
          ))}
        </div>
      )}
      {file && (
        <>
          {/* eslint-disable-next-line @next/next/no-img-element -- the user's own post behind the BFF */}
          <img className="h-result-img" src={fileUrl(file.name)} alt={`${file.label}${file.slide ? `, slide ${file.slide}` : ""}`} data-testid="result-img" />
          {shown.length > 1 && (
            <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 10 }}>
              <button className="h-btn-ghost" aria-label="Previous slide" disabled={slide === 0} onClick={() => setSlide((i) => i - 1)}><i className="ti ti-chevron-left" /></button>
              <span className="h-muted" style={{ fontSize: 13 }} data-testid="result-slide">Slide {slide + 1} of {shown.length}</span>
              <button className="h-btn-ghost" aria-label="Next slide" disabled={slide >= shown.length - 1} onClick={() => setSlide((i) => i + 1)}><i className="ti ti-chevron-right" /></button>
            </div>
          )}
        </>
      )}
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <a className="h-btn-solid" href={`/api/posts/${post.id}/zip`} data-testid="result-zip" style={{ textDecoration: "none", gap: 6 }}>
          <i className="ti ti-file-zip" /> Download everything
        </a>
        {file && (
          <a className="h-btn-ghost" href={fileUrl(file.name)} download={file.name} style={{ textDecoration: "none", gap: 6 }}>
            <i className="ti ti-download" /> This one
          </a>
        )}
      </div>

      <section className="h-studio-panel" style={{ padding: 14 }}>
        <div className="h-studio-step"><i className="ti ti-message-2" /> Captions in your voice</div>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          {PLATFORMS.map((p) => (
            <button key={p.key} className="h-size-chip" aria-pressed={platforms.includes(p.key)} data-testid={`platform-${p.key}`}
              onClick={() => setPlatforms((ps) => ps.includes(p.key) ? ps.filter((x) => x !== p.key) : [...ps, p.key])}>
              <i className={`ti ti-${p.icon}`} /> {p.label}
            </button>
          ))}
        </div>
        <input className="h-input" value={note} maxLength={300} onChange={(e) => setNote(e.target.value)} placeholder="Anything to mention? (optional) e.g. open till 10 pm this week" />
        <button className="h-btn-solid" style={{ alignSelf: "flex-start", gap: 6 }} disabled={writing || !platforms.length} onClick={() => void write()} data-testid="write-captions">
          <i className="ti ti-sparkles" /> {writing ? "Writing…" : Object.keys(post.captions).length ? "Write them again" : "Write captions"}
        </button>
        {Object.entries(post.captions).map(([k, c]) => <CaptionBox key={`${k}:${c.text}`} post={post} platform={k} c={c} onSaved={update} />)}
      </section>

      <section className="h-studio-panel" style={{ padding: 14 }}>
        <div className="h-studio-step"><i className="ti ti-user-check" /> Send to your client for approval</div>
        {status !== "none" && (
          <span data-testid="review-status">
            {status === "waiting" && <span className="h-badge">Waiting for your client</span>}
            {status === "approved" && <span className="h-badge" data-tone="ok"><i className="ti ti-check" /> Approved</span>}
            {status === "changes" && <span className="h-badge" data-tone="warn">Changes asked</span>}
            {post.review_comment && <span style={{ display: "block", fontSize: 13, marginTop: 6 }}>“{post.review_comment}”</span>}
          </span>
        )}
        {link
          ? <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              <input className="h-input" readOnly value={link.url} data-testid="review-url" onFocus={(e) => e.currentTarget.select()} />
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                <button className="h-btn-solid" onClick={() => void copyLink()} style={{ gap: 6 }}><i className={`ti ti-${copied ? "check" : "copy"}`} /> {copied ? "Copied" : "Copy link"}</button>
                <a className="h-btn-ghost" style={{ textDecoration: "none", gap: 6 }} target="_blank" rel="noopener noreferrer"
                  href={`https://wa.me/?text=${encodeURIComponent(`Here's the post for your approval: ${link.url}`)}`}><i className="ti ti-brand-whatsapp" /> WhatsApp</a>
                <a className="h-btn-ghost" style={{ textDecoration: "none", gap: 6 }}
                  href={`mailto:?subject=${encodeURIComponent("A post for your approval")}&body=${encodeURIComponent(`Hi! Here's the post, please approve it or tell me what to change: ${link.url}`)}`}><i className="ti ti-mail" /> Email</a>
              </div>
              <span className="h-muted" style={{ fontSize: 12 }}>Anyone with this link can see this post and approve it, until {new Date(link.expires_at).toLocaleDateString()}. You&apos;ll get a notification when they answer.</span>
            </div>
          : <button className="h-btn-ghost" style={{ alignSelf: "flex-start", gap: 6 }} disabled={linkBusy} onClick={() => void share()} data-testid="review-link">
              <i className="ti ti-link" /> {linkBusy ? "Making a link…" : status === "none" ? "Get a review link" : "Get a new review link"}
            </button>}
      </section>
      {refusal && <Upgrade r={refusal} />}
    </div>
  )
}
