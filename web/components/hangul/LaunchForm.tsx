"use client"

import { useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import { isRefusal, KIND_ICON, launchApi, type Kinds } from "@/lib/launch"

/**
 * The questions a launch plan needs: what, where, how big, renting or not,
 * budget and when. Kind and size are tiles/chips; the rest are optional. The
 * plan is made at once (estimates), and live prices start in the background
 * when the user's plan includes them.
 */
const RENTING: Array<[string, string]> = [["yes", "Renting a place"], ["own", "My own / family space"], ["no", "No place needed"]]

export function LaunchForm({ onCancel }: { onCancel?: () => void }) {
  const router = useRouter()
  const [catalogue, setCatalogue] = useState<Kinds | null>(null)
  const [kind, setKind] = useState("")
  const [size, setSize] = useState("")
  const [city, setCity] = useState("")
  const [area, setArea] = useState("")
  const [renting, setRenting] = useState("yes")
  const [budget, setBudget] = useState("")
  const [start, setStart] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    void launchApi.kinds().then((r) => {
      if (isRefusal(r)) setError(r.detail)
      else setCatalogue(r)
    })
  }, [])

  const k = catalogue?.kinds.find((x) => x.key === kind)
  const budgetNum = budget.trim() ? Number(budget.replace(/[,₹\s]/g, "")) : null
  const ready = Boolean(k && size && city.trim() && (budgetNum === null || (Number.isFinite(budgetNum) && budgetNum >= 0)))

  const submit = async () => {
    if (!ready) return
    setBusy(true)
    setError(null)
    const r = await launchApi.create({ kind, size, city: city.trim(), area: area.trim(), renting, budget: budgetNum, start: start.trim() })
    setBusy(false)
    if (isRefusal(r)) setError(r.detail)
    else router.push(`/launch/${r.plan.id}`)
  }

  return (
    <section className="h-studio-panel h-launch-form" data-testid="launch-form">
      <div className="h-studio-step"><b>1</b> What do you want to start?</div>
      <div className="h-launch-kinds">
        {(catalogue?.kinds ?? []).map((x) => (
          <button key={x.key} className="h-launch-kind" aria-pressed={kind === x.key} data-testid={`launch-kind-${x.key}`}
            onClick={() => { setKind(x.key); setSize(""); if (x.key === "d2c_brand") setRenting("no") }}>
            <i className={`ti ti-${KIND_ICON[x.key] ?? "building"}`} />
            <b>{x.label}</b>
            <span>{x.blurb}</span>
          </button>
        ))}
      </div>
      {k && (
        <>
          <div className="h-studio-step"><b>2</b> How big will it start?</div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {k.sizes.map((s) => (
              <button key={s.key} className="h-size-chip" aria-pressed={size === s.key} data-testid={`launch-size-${s.key}`}
                onClick={() => setSize(s.key)}>{s.label}</button>
            ))}
          </div>
          <div className="h-studio-step"><b>3</b> Where?</div>
          <div className="h-launch-row">
            <label className="h-field"><span>City</span>
              <input className="h-input" value={city} onChange={(e) => setCity(e.target.value)} placeholder="Srinagar" maxLength={80} data-testid="launch-city" />
            </label>
            <label className="h-field"><span>Area <small>(optional)</small></span>
              <input className="h-input" value={area} onChange={(e) => setArea(e.target.value)} placeholder="Rajbagh" maxLength={120} data-testid="launch-area" />
            </label>
          </div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }} aria-label="Your place">
            {RENTING.map(([key, label]) => (
              <button key={key} className="h-size-chip" aria-pressed={renting === key}
                data-testid={`launch-renting-${key}`} onClick={() => setRenting(key)}>{label}</button>
            ))}
          </div>
          <div className="h-studio-step"><b>4</b> Budget and timing <small className="h-muted" style={{ fontWeight: 400 }}>(optional)</small></div>
          <div className="h-launch-row">
            <label className="h-field"><span>Budget in ₹</span>
              <input className="h-input" inputMode="numeric" value={budget} onChange={(e) => setBudget(e.target.value)} placeholder="10,00,000" data-testid="launch-budget" />
            </label>
            <label className="h-field"><span>When do you want to open?</span>
              <input className="h-input" value={start} onChange={(e) => setStart(e.target.value)} placeholder="In 3 months" maxLength={60} />
            </label>
          </div>
        </>
      )}
      {catalogue && !catalogue.access.allowed && catalogue.access.reason !== "not_asked" && (
        <p className="h-muted" style={{ fontSize: 13, margin: 0 }} data-testid="launch-access-note">{catalogue.access.detail}</p>
      )}
      {error && <span role="alert" style={{ color: "var(--err)", fontSize: 13 }}>{error}</span>}
      <div style={{ display: "flex", gap: 8 }}>
        <button className="h-btn-solid" disabled={!ready || busy} onClick={() => void submit()} data-testid="launch-submit">
          {busy ? "Making your plan…" : "Make my plan"}
        </button>
        {onCancel && <button className="h-btn-ghost" onClick={onCancel}>Cancel</button>}
      </div>
    </section>
  )
}
