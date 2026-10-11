"use client"

import Link from "next/link"
import { useState } from "react"
import { fileUrl, isRefusal } from "@/lib/brands"
import { missionsApi, rupees, type Mission, type Report, type Step, type Trust } from "@/lib/missions"

/**
 * Missions: jobs Hangul carries through on its own (backend `harness/missions`).
 * A mission is a checklist that ticks itself; the owner only decides where a
 * step is waiting for them. Used by /missions and /missions/[id].
 */

const STEP_ICON: Record<Step["state"], string> = {
  done: "circle-check", waiting: "hand-stop", todo: "circle-dashed", skipped: "circle-minus", failed: "alert-triangle",
}

const STATUS: Record<Mission["status"], { label: string; tone?: string }> = {
  waiting: { label: "Needs you", tone: "warn" },
  active: { label: "Working on it", tone: "brand" },
  done: { label: "Done", tone: "ok" },
  cancelled: { label: "Called off" },
  expired: { label: "Expired" },
}

function dayLabel(iso: string) {
  return new Date(`${iso}T12:00:00`).toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "short" })
}

function Verdict({ m }: { m: Mission }) {
  const o = m.data.outcome
  if (!o) return null
  const title = o.verdict === "worked" ? "It worked" : o.verdict === "helped" ? "It may have helped" : "No clear effect"
  return (
    <div className="h-mission-verdict" data-verdict={o.verdict} data-testid="mission-verdict">
      <strong>{title}</strong>
      <span>Sold {rupees(o.actual)} against the {rupees(o.expected)} expected ({o.lift >= 0 ? "+" : "−"}{rupees(o.lift)}).</span>
      {o.verdict === "helped" && <span className="h-muted">That&apos;s inside the forecast&apos;s usual error, so it may be chance.</span>}
    </div>
  )
}

export function MissionCard({ m, onChange, full = false }: { m: Mission; onChange: (m: Mission) => void; full?: boolean }) {
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const st = STATUS[m.status]
  const idea = m.data.idea
  const preview = m.data.files?.[0]

  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true); setError(null)
    const r = await fn()
    setBusy(false)
    if (isRefusal(r)) { setError(r.detail); return }
    const next = r as Mission & { message?: string }
    if (next.message) setNote(next.message)
    onChange(next)
  }

  return (
    <article className="h-studio-panel h-mission" data-status={m.status} data-testid={`mission-${m.id}`}>
      <header className="h-mission-head">
        <div>
          <div className="h-mission-title">
            {m.data.business_name}: {m.data.weekday} looks slow
          </div>
          <div className="h-muted" style={{ fontSize: 13 }}>{dayLabel(m.target_day)}</div>
        </div>
        <span className="h-badge" data-tone={st.tone}>{st.label}</span>
      </header>
      <div className="h-biz-progress" aria-label={`${m.done} of ${m.total} steps done`}>
        <span style={{ width: `${(m.done / Math.max(1, m.total)) * 100}%` }} />
      </div>
      <ol className="h-mission-steps">
        {m.steps.map((s) => (
          <li key={s.key} data-state={s.state}>
            <i className={`ti ti-${STEP_ICON[s.state]}`} aria-hidden />
            <div>
              <div>{s.label}</div>
              {s.note && <div className="h-muted">{s.note}</div>}
            </div>
          </li>
        ))}
      </ol>

      {(m.status === "waiting" || full) && idea && (
        <div className="h-mission-idea">
          {preview && m.data.post_id && (
            <Link href={`/brands/${m.data.brand_id}?tab=posts&post=${m.data.post_id}`} className="h-mission-preview">
              {/* eslint-disable-next-line @next/next/no-img-element -- a file from the user's folder, served by the BFF */}
              <img src={fileUrl(preview)} alt={`The post for ${idea.title}`} />
            </Link>
          )}
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <strong>{idea.title}</strong>
            <span>{idea.idea}</span>
            {idea.margin_note && <span className="h-muted">{idea.margin_note}</span>}
            {idea.track_note && <span className="h-muted">{idea.track_note}</span>}
          </div>
        </div>
      )}

      {m.status === "waiting" && (
        <div className="h-mission-actions">
          <button className="h-btn-solid" disabled={busy} data-testid="mission-approve"
            onClick={() => act(() => missionsApi.decide(m.id, "approve"))}>Go ahead</button>
          <button className="h-btn-outline" disabled={busy} data-testid="mission-reject"
            onClick={() => act(() => missionsApi.decide(m.id, "reject"))}>Not this time</button>
        </div>
      )}

      {full && m.data.share_text && m.data.approved && !m.data.undone && (
        <div className="h-mission-share">
          <div className="h-muted" style={{ fontSize: 13 }}>Forward this to your regulars:</div>
          <pre>{m.data.share_text.replace(/\*/g, "")}</pre>
          <button className="h-btn-ghost" onClick={() => void navigator.clipboard?.writeText(m.data.share_text!.replace(/\*/g, ""))}>
            <i className="ti ti-copy" /> Copy
          </button>
        </div>
      )}

      <Verdict m={m} />

      {m.can_undo && (
        <div className="h-mission-actions">
          <button className="h-btn-ghost" disabled={busy} data-testid="mission-undo" onClick={() => act(() => missionsApi.undo(m.id))}>
            <i className="ti ti-arrow-back-up" /> Undo{m.data.auto ? " (and ask me first next time)" : ""}
          </button>
        </div>
      )}

      {full && m.data.trust_offer && !m.data.trust_answered && m.trust && !m.trust.auto && m.business_id && (
        <TrustOffer businessId={m.business_id} name={m.data.business_name ?? ""} after={m.trust_after ?? 3}
          onDone={() => void missionsApi.get(m.id).then((r) => { if (!isRefusal(r)) onChange(r) })} />
      )}

      {note && <p className="h-mission-note" role="status">{note.replace(/\*/g, "")}</p>}
      {error && <span role="alert" style={{ color: "var(--err)", fontSize: 13 }}>{error}</span>}
      {!full && <Link href={`/missions/${m.id}`} className="h-mission-more">Open <i className="ti ti-chevron-right" /></Link>}
    </article>
  )
}

function TrustOffer({ businessId, name, after, onDone }: { businessId: number; name: string; after: number; onDone: () => void }) {
  const [busy, setBusy] = useState(false)
  return (
    <div className="h-mission-trust" data-testid="trust-offer">
      <span>You&apos;ve said yes to my last {after} slow-day offers for {name}. Shall I go ahead on my own next time? I&apos;ll still tell you, and you can undo it.</span>
      <button className="h-btn-solid" disabled={busy}
        onClick={async () => { setBusy(true); await missionsApi.setTrust(businessId, true); setBusy(false); onDone() }}>Yes, go ahead</button>
    </div>
  )
}

export function MonthCard({ r, title }: { r: Report; title: string }) {
  if (!r.spotted) return null
  return (
    <section className="h-studio-panel" data-testid="mission-month">
      <div className="h-mission-title">{title}</div>
      <div className="h-launch-tiles">
        <div className="h-launch-tile"><div className="h-launch-tile-label">Slow days spotted</div><div className="h-launch-tile-value">{r.spotted}</div></div>
        <div className="h-launch-tile">
          <div className="h-launch-tile-label">Offers run</div><div className="h-launch-tile-value">{r.went_ahead}</div>
          {r.on_their_own > 0 && <div className="h-launch-tile-sub">{r.on_their_own} on my own</div>}
        </div>
        <div className="h-launch-tile">
          <div className="h-launch-tile-label">Above forecast</div>
          <div className="h-launch-tile-value" data-testid="mission-lift">{r.measured ? `${r.lift < 0 ? "−" : ""}${rupees(r.lift)}` : "–"}</div>
          <div className="h-launch-tile-sub" data-tone={r.lift > 0 ? "ok" : undefined}>
            {r.measured ? `estimate, from ${r.measured} measured day${r.measured === 1 ? "" : "s"}` : "log your sales to measure"}
          </div>
        </div>
      </div>
      {r.best && <span className="h-muted" style={{ fontSize: 13 }}>Best: {r.best.idea} on {dayLabel(r.best.day)}, +{rupees(r.best.lift)}.</span>}
      {r.price && <span className="h-muted" style={{ fontSize: 13 }}>{r.price} a month.</span>}
    </section>
  )
}

export function TrustList({ trust, onChange }: { trust: Trust[]; onChange: () => void }) {
  if (!trust.length) return null
  return (
    <section className="h-studio-panel" data-testid="mission-trust">
      <div className="h-mission-title">Going ahead without asking</div>
      <span className="h-muted" style={{ fontSize: 13 }}>
        When this is on, Hangul goes ahead with a slow-day offer and tells you after, with an Undo. A &quot;Not this time&quot; or an undo turns it back off.
      </span>
      {trust.map((t) => (
        <label key={t.scope} className="h-mission-trust-row">
          <input type="checkbox" checked={t.auto} data-testid={`trust-${t.business_id}`}
            onChange={async (e) => { await missionsApi.setTrust(t.business_id!, e.target.checked); onChange() }} />
          <span>{t.business_name}</span>
          <span className="h-muted">{t.auto ? "On" : `${t.streak} yes in a row`}</span>
        </label>
      ))}
    </section>
  )
}
