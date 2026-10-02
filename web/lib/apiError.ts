/**
 * The BFF answers every failure with `{ detail, code }`. The AI SDK surfaces a
 * failed request as an Error whose message is the response body, and our own
 * fetch calls get the Response — this normalises both into one shape the UI
 * can branch on.
 */
export type ApiFailure = { code: string; detail: string; planNeeded?: string | null }

/** The 402 codes from the plan check: shown as an upgrade card, not an error. */
export const BILLING_CODES = ["plan_required", "effort_not_allowed", "research_requires_plan", "insufficient_balance", "free_pool_exhausted"]
export const isBillingFailure = (f: ApiFailure | null | undefined) => Boolean(f && BILLING_CODES.includes(f.code))

const withPlan = (j: { planNeeded?: unknown }) => (typeof j.planNeeded === "string" ? { planNeeded: j.planNeeded } : {})

export function parseApiFailure(input: unknown): ApiFailure {
  const fallback: ApiFailure = { code: "unknown", detail: "Something went wrong. Please try again." }
  const text = input instanceof Error ? input.message : typeof input === "string" ? input : ""
  if (!text) return fallback
  try {
    const j = JSON.parse(text)
    if (j && typeof j.detail === "string") return { code: typeof j.code === "string" ? j.code : "unknown", detail: j.detail, ...withPlan(j) }
  } catch { /* not JSON */ }
  // Network-level failures from fetch itself.
  if (/failed to fetch|networkerror|load failed/i.test(text)) {
    return { code: "network", detail: "Couldn't reach the server. Check your connection." }
  }
  return { code: "unknown", detail: text }
}

export async function failureFromResponse(res: Response): Promise<ApiFailure> {
  try {
    const j = await res.json()
    if (j && typeof j.detail === "string") return { code: typeof j.code === "string" ? j.code : "unknown", detail: j.detail, ...withPlan(j) }
  } catch { /* not JSON */ }
  if (res.status === 401) return { code: "unauthorized", detail: "Sign in to continue." }
  if (res.status === 429) return { code: "rate_limited", detail: "Too many requests. Please slow down." }
  return { code: "unknown", detail: `Request failed (${res.status}).` }
}
