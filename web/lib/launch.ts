/**
 * Launch plans, client side: types mirroring backend `harness/launch` and
 * `db/launch.py::view`, and the calls the /launch pages make.
 */
import { json, type Refusal } from "@/lib/brands"

export type Seller = { seller: string; price: number; url: string; quote?: string }
export type Item = {
  key: string; name: string; category: string; monthly: boolean; qty: number; low: number; high: number; typical: number
  amount: number; include: boolean; status: "estimate" | "sourced" | "user"; sellers: Seller[]; checked_at: string | null
  why: string; search: string; local: string
}
export type Benchmark = {
  key: string; label: string; typical: string; value: string; status: "estimate" | "sourced"
  source: { url: string; title: string } | null; quote: string; checked_at: string | null
}
export type Supplier = { query: string; near: string; search_link: string; places: Array<{ name: string; address: string; type?: string; link?: string }> }
export type Variable = { key: string; label: string; pct: number }
export type Assumptions = { price: number; units_per_day: number; days_per_month: number; working_capital_months: number; variable: Variable[] }
export type Month = {
  revenue: number; variable_costs: number; contribution_per_sale: number; fixed: number; profit: number
  margin: number | null; breakeven_per_day: number | null; units_per_day: number; payback_months?: number | null
}
export type Economics = Month & {
  price: number; days_per_month: number; variable_share: number; one_off: number; working_capital: number
  working_capital_months: number; startup_total: number; payback_months: number | null
  budget: number | null; budget_gap: number | null; by_category: Record<string, number>
  scenarios: Record<"worst" | "likely" | "best", Month>
  chart: Array<{ units_per_day: number; revenue: number; costs: number }>
}
export type Access = { allowed: boolean; reason: string | null; detail: string; plan_needed: string | null; left: number | null }
export type Plan = {
  id: number; title: string; kind: string; city: string; area: string; conversation_id: string | null
  answers: { size: string; renting: string; budget: number | null; start: string; note: string }
  items: Item[]; assumptions: Assumptions; benchmarks: Benchmark[]; suppliers: Supplier[]
  status: "ready" | "sourcing" | "failed"; error: string; sourced: boolean
  progress: { stage?: string; done?: number; total?: number }; refreshes: number
  created_at: string | null; updated_at: string | null; economics: Economics
}
export type PlanSummary = Pick<Plan, "id" | "title" | "kind" | "city" | "area" | "status" | "sourced" | "created_at" | "updated_at"> & {
  startup_total: number; breakeven_per_day: number | null; profit: number; payback_months: number | null
}
export type Kind = { key: string; label: string; blurb: string; unit: string; sizes: Array<{ key: string; label: string }> }
export type Kinds = { kinds: Kind[]; renting: string[]; access: Access }
export type NewPlan = {
  kind: string; city: string; area?: string; size: string; renting?: string; budget?: number | null; start?: string; note?: string; live?: boolean
}
export type Patch = {
  price?: number; units_per_day?: number; days_per_month?: number; working_capital_months?: number
  variable?: Record<string, number>; items?: Record<string, { amount?: number; qty?: number; include?: boolean }>; title?: string
}

/** backend kinds.CATEGORIES, in the order the checklist shows them */
export const CATEGORIES: Array<[string, string, string]> = [
  ["equipment", "Equipment", "tools-kitchen-2"],
  ["space", "Space and fit-out", "building-store"],
  ["licence", "Licences and registration", "license"],
  ["stock", "Opening stock", "packages"],
  ["software", "Software and online", "device-laptop"],
  ["marketing", "Launch marketing", "speakerphone"],
  ["staff", "Staff (monthly)", "users"],
  ["running", "Running costs (monthly)", "receipt"],
]

export const KIND_ICON: Record<string, string> = {
  cloud_kitchen: "chef-hat", cafe: "coffee", retail_shop: "building-store", salon: "scissors", d2c_brand: "package",
}

/** Indian grouping: ₹1,25,000; big numbers as lakh / crore. */
export function rupees(v: number | null | undefined, compact = false): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—"
  const sign = v < 0 ? "−" : ""
  const a = Math.abs(v)
  if (compact && a >= 1e7) return `${sign}₹${(a / 1e7).toFixed(a >= 1e8 ? 0 : 1)} Cr`
  if (compact && a >= 1e5) return `${sign}₹${(a / 1e5).toFixed(a >= 1e6 ? 0 : 1)} L`
  return `${sign}₹${Math.round(a).toLocaleString("en-IN")}`
}

const send = (url: string, method: string, body?: unknown) =>
  fetch(url, { method, headers: body === undefined ? undefined : { "Content-Type": "application/json" },
               body: body === undefined ? undefined : JSON.stringify(body) }).catch(() => null)

export const launchApi = {
  kinds: () => fetch("/api/launch/kinds", { cache: "no-store" }).catch(() => null).then((r) => json<Kinds>(r)),
  list: () => fetch("/api/launch", { cache: "no-store" }).catch(() => null).then((r) => json<PlanSummary[]>(r)),
  get: (id: number) => fetch(`/api/launch/${id}`, { cache: "no-store" }).catch(() => null).then((r) => json<Plan>(r)),
  create: (body: NewPlan) => send("/api/launch", "POST", body).then((r) => json<{ plan: Plan; access: Access }>(r)),
  patch: (id: number, body: Patch) => send(`/api/launch/${id}`, "PATCH", body).then((r) => json<Plan>(r)),
  source: (id: number) => send(`/api/launch/${id}/source`, "POST").then((r) => json<Plan>(r)),
  refresh: (id: number, key: string) => send(`/api/launch/${id}/items/${key}/refresh`, "POST").then((r) => json<Plan>(r)),
  remove: (id: number) => send(`/api/launch/${id}`, "DELETE"),
}

export const isRefusal = (v: unknown): v is Refusal =>
  Boolean(v && typeof v === "object" && "detail" in (v as object) && !("id" in (v as object)) && !("plan" in (v as object)))
