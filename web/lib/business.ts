/**
 * How's business, client side: types mirroring backend `harness/sales/service.overview`
 * and the calls the /business page makes.
 */
import { json, type Refusal } from "@/lib/brands"

export type Business = {
  id: number; name: string; kind: string; city: string; brand_id: number | null; launch_plan_id: number | null
  nudges: boolean; paused: boolean
}
export type Access = { plan: string | null; forecast: boolean; reasons: boolean; ideas: "all" | "weekly" | "none"; whatsapp: boolean }
export type Listing = { businesses: Business[]; slots: number; can_add: boolean; access: Access; kinds: Array<{ key: string; label: string }> }
export type Day = {
  day: string; sales: number; bills: number | null; closed: boolean; partial: boolean; promo: boolean; source: string; note: string
  rain_mm: number | null; tmax: number | null
}
export type Reason = { key: string; label: string; effect: number }
export type Forecast = {
  status: "learning" | "ready" | "closed"; day?: string; days_logged: number; days_needed: number
  value?: number | null; low?: number | null; high?: number | null; model?: string | null; model_label?: string
  accuracy?: number | null; backtest_days?: number; beats_baseline?: boolean; typical?: number | null
  reasons?: Reason[]; notes?: string[]
}
export type Idea = {
  key: string; title: string; idea: string; layout: string; headline: string; subline: string; discount: number
  discount_cut: boolean; price: string; cta: string; share: string; cause: string; left_per_sale: number | null; margin_note: string
}
export type Overview = {
  business: Business; today: string; tomorrow: string; access: Access
  week: { total: number; days: number; bills: number; last_week_same_days: number | null; change: number | null; best: string | null }
  days: Day[]; expected?: Array<{ day: string; expected: number }>
  plan: { breakeven?: number | null; price?: number; plan_title?: string; planned_per_day?: number | null }
  avg_bill: number | null; weather_tomorrow: { rain_mm: number | null; tmax: number | null } | null
  festival_tomorrow: string | null; logged_today: boolean
  forecast: Forecast | null; slow: { slow: boolean; why: string; breakeven: number | null } | null
  ideas: Idea[]; ideas_left: number | null; locked: Array<{ feature: string; plan: string }>
}
export type Imported = {
  days: Array<{ day: string; sales: number; bills: number }>; date_col: string; amount_col: string; rows_used: number
  rows_skipped: number; columns: string[]; notes: string[]; from: string | null; to: string | null; total: number
  future_skipped: number; saved: { added: number; replaced: number; kept: number } | null
}

const send = (url: string, method: string, body?: unknown) =>
  fetch(url, { method, headers: body === undefined ? undefined : { "Content-Type": "application/json" },
               body: body === undefined ? undefined : JSON.stringify(body) }).catch(() => null)

export const businessApi = {
  list: () => fetch("/api/business", { cache: "no-store" }).catch(() => null).then((r) => json<Listing>(r)),
  create: (body: Partial<Business>) => send("/api/business", "POST", body).then((r) => json<Business>(r)),
  patch: (id: number, body: Partial<Business> & { unlink?: string[] }) => send(`/api/business/${id}`, "PATCH", body).then((r) => json<Business>(r)),
  overview: (id: number) => fetch(`/api/business/${id}/overview`, { cache: "no-store" }).catch(() => null).then((r) => json<Overview>(r)),
  log: (id: number, body: { day?: string; sales?: number; bills?: number | null; closed?: boolean; add?: boolean }) =>
    send(`/api/business/${id}/days`, "POST", body).then((r) => json<Day>(r)),
  removeDay: (id: number, day: string) => send(`/api/business/${id}/days/${day}`, "DELETE"),
  importFile: (id: number, file: File, opts: { preview?: boolean; date_col?: string; amount_col?: string; replace?: boolean }) => {
    const form = new FormData()
    form.append("file", file)
    for (const [k, v] of Object.entries(opts)) if (v !== undefined && v !== "") form.append(k, String(v))
    return fetch(`/api/business/${id}/import`, { method: "POST", body: form }).catch(() => null).then((r) => json<Imported>(r))
  },
  useIdea: (id: number, key: string) => send(`/api/business/${id}/ideas/${key}/use`, "POST").then((r) => json<{ studio_url: string }>(r)),
}

export const isRefusal = (v: unknown): v is Refusal =>
  Boolean(v && typeof v === "object" && "detail" in (v as object) && !("id" in (v as object)) && !("business" in (v as object))
    && !("businesses" in (v as object)) && !("day" in (v as object)) && !("days" in (v as object)) && !("studio_url" in (v as object)))

export const WEEKDAY = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
export const dayName = (iso: string) => WEEKDAY[new Date(iso + "T12:00:00").getDay()]
export const shortDate = (iso: string) => new Date(iso + "T12:00:00").toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short" })
