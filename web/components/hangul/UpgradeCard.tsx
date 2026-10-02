"use client"

import Link from "next/link"
import type { ApiFailure } from "@/lib/apiError"

const PLAN_LABEL: Record<string, string> = { plus: "Plus", pro: "Pro" }

/**
 * Shown in the thread instead of the error notice when a run is refused by
 * the plan check (402): the model / effort / mode needs a paid plan, the
 * period's allowance is used up, or the month's shared free capacity is.
 */
export function UpgradeCard({ failure, onDismiss }: { failure: ApiFailure; onDismiss: () => void }) {
  const plan = failure.planNeeded ?? (failure.code === "insufficient_balance" ? null : "plus")
  // both are "no money left to spend", so credits are an answer as well as upgrading
  const outOfBalance = failure.code === "insufficient_balance" || failure.code === "free_pool_exhausted"
  return (
    <div
      className="rounded-xl p-3"
      data-testid="upgrade-card"
      data-code={failure.code}
      style={{ background: "var(--warn-bg)", border: "0.5px solid var(--warn)" }}
    >
      <p className="text-sm" style={{ margin: 0 }}>
        <i className="ti ti-lock" style={{ fontSize: 13, marginRight: 6 }} />
        {failure.detail}
      </p>
      <div className="flex gap-2" style={{ marginTop: 8, flexWrap: "wrap" }}>
        {plan && (
          <Link href={`/billing?upgrade=${plan}`} className="h-btn-solid" style={{ textDecoration: "none" }} data-testid="upgrade-link">
            Upgrade to {PLAN_LABEL[plan] ?? plan}
          </Link>
        )}
        {outOfBalance && (
          <Link href="/billing?topup=1" className={plan ? "h-btn-ghost" : "h-btn-solid"} style={{ textDecoration: "none" }}>
            Buy credits
          </Link>
        )}
        <button className="h-btn-ghost" onClick={onDismiss}>Dismiss</button>
      </div>
    </div>
  )
}
